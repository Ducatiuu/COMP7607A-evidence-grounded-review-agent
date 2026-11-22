from collections import deque

from src.controllers import DynamicAgent, QueryParser
from src.llm_client import LLMRequest, LLMResponse, MockLLMClient
from src.tools import AnalysisContext
from src.verification import Finalizer
from test_tools import _dataset


QUERY = {"task_type": "rate", "categories": ["service"], "metric": "negative_rate", "denominator_spec": "aspect_mentions"}


def _answer(negative_count=2):
    return {"status": "ok", "answer_text": f"{negative_count} of 3 service records are negative.",
            "numeric_claims": [{"metric": "negative_rate", "category": "service", "scope_ids": ["R01", "R02", "R03", "R04"],
                                "value": negative_count / 3, "numerator": negative_count, "denominator": 3}],
            "denominator_explanation": "Among three service mentions."}


def _agent(decisions, answer=None):
    parser_client = MockLLMClient(deque([LLMResponse(content=QUERY, model="mock")]))
    answer_client = MockLLMClient(deque([LLMResponse(content=answer or _answer(), model="mock")]))
    decider = MockLLMClient(deque(decisions))
    agent = DynamicAgent(QueryParser(parser_client, "mock"), decider, Finalizer(answer_client, "mock"), "mock")
    return agent, decider, answer_client


def _decision(action, calls=None):
    return LLMResponse(content={"action": action, "calls": calls or []}, model="mock")


def _aggregate_call():
    return {"name": "aggregate_aspects", "arguments": {"categories": ["service"], "metric": "negative_rate", "denominator_spec": "aspect_mentions"}}


def test_dynamic_tool_result_is_in_next_model_request_and_can_finish():
    agent, decider, _ = _agent([_decision("call_tools", [_aggregate_call()]), _decision("finish")])
    answer = agent.run(ctx=_dataset(), question="What is the negative service rate?", question_id="Q1")
    assert answer.status == "ok" and answer.numeric_claims[0].value == 2 / 3
    assert answer.usage["decision_rounds"] == 2 and answer.usage["analysis_tool_calls"] == 1
    assert answer.usage["api_requests"] == 4  # parser + two decisions + answer
    assert decider.requests[1].payload["history"][0]["data"]["stats"][0]["negative_count"] == 2
    assert {tool["name"] for tool in decider.requests[0].payload["available_tools"]} == {"filter_records", "aggregate_aspects", "compare_aspects", "get_evidence"}


def test_four_empty_finish_decisions_exhaust_rounds_without_final_answer():
    agent, decider, answer_client = _agent([_decision("finish") for _ in range(4)])
    answer = agent.run(ctx=_dataset(), question="What is the negative service rate?")
    assert answer.status == "failed" and answer.error_code == "insufficient_evidence"
    assert answer.usage["decision_rounds"] == 4 and answer.usage["analysis_tool_calls"] == 0
    assert len(decider.requests) == 4 and answer_client.requests == []


def test_parallel_calls_stop_before_seventh_dispatch():
    bad_calls = [{"name": "unknown", "arguments": {"index": i}} for i in range(7)]
    agent, decider, answer_client = _agent([_decision("call_tools", bad_calls)])
    answer = agent.run(ctx=_dataset(), question="What is the negative service rate?")
    assert answer.status == "failed" and answer.error_code == "budget_exceeded"
    assert answer.usage["analysis_tool_calls"] == 6 and answer.usage["decision_rounds"] == 1
    assert len([event for event in answer.tool_trace if event.stage == "analysis_tool"]) == 6
    assert len(decider.requests) == 1 and answer_client.requests == []


def test_invalid_duplicate_and_recovered_calls_all_count():
    calls = [
        {"name": "run_python", "arguments": {}},
        {"name": "aggregate_aspects", "arguments": {"categories": ["invalid"]}},
        _aggregate_call(),
        _aggregate_call(),
    ]
    agent, _, _ = _agent([_decision("call_tools", calls), _decision("finish")])
    answer = agent.run(ctx=_dataset(), question="What is the negative service rate?")
    assert answer.status == "ok" and answer.usage["analysis_tool_calls"] == 4
    tool_events = [event for event in answer.tool_trace if event.stage == "analysis_tool"]
    assert [event.error for event in tool_events] == ["unknown_tool", "invalid_tool_arguments_or_scope", None, "duplicate_call"]


def test_invalid_decision_and_timeout_consume_rounds():
    agent, decider, _ = _agent([LLMResponse(content={"action": "call_tools", "calls": []}, model="mock"), TimeoutError(),
                               _decision("call_tools", [_aggregate_call()]), _decision("finish")])
    answer = agent.run(ctx=_dataset(), question="What is the negative service rate?")
    assert answer.status == "ok" and answer.usage["decision_rounds"] == 4
    assert len([event for event in answer.tool_trace if event.stage == "decision" and event.status == "invalid"]) == 2
    assert len(decider.requests) == 4


def test_dynamic_answer_repair_is_separate_from_decision_budget():
    parser_client = MockLLMClient(deque([LLMResponse(content=QUERY, model="mock")]))
    decider = MockLLMClient(deque([_decision("call_tools", [_aggregate_call()]), _decision("finish")]))
    bad = _answer()
    bad["numeric_claims"][0]["value"] = 0.5
    answer_client = MockLLMClient(deque([LLMResponse(content=bad, model="mock"), LLMResponse(content=_answer(), model="mock")]))
    agent = DynamicAgent(QueryParser(parser_client, "mock"), decider, Finalizer(answer_client, "mock"), "mock")
    answer = agent.run(ctx=_dataset(), question="What is the negative service rate?")
    assert answer.status == "ok" and answer.usage["output_repairs"] == 1
    assert answer.usage["decision_rounds"] == 2 and answer.usage["analysis_tool_calls"] == 1
    assert answer.usage["api_requests"] == 5
    assert [request.stage for request in answer_client.requests] == ["answer", "answer_repair"]


class BranchingClient:
    def __init__(self):
        self.requests: list[LLMRequest] = []

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        history = request.payload["history"]
        if not history:
            return _decision("call_tools", [_aggregate_call()])
        negative = history[0]["data"]["stats"][0]["negative_count"]
        if negative and len(history) == 1:
            return _decision("call_tools", [{"name": "get_evidence", "arguments": {"record_ids": ["R01", "R02"]}}])
        return _decision("finish")


def test_next_action_changes_with_actual_tool_feedback():
    positive_context = _dataset()
    zero_dataset = _dataset().dataset.model_copy(deep=True)
    for extraction in zero_dataset.extractions:
        for aspect in extraction.aspects:
            if aspect.category.value == "service":
                aspect.sentiment = "neutral"
    zero_context = AnalysisContext(zero_dataset)
    observed = []
    for ctx, count in [(positive_context, 2), (zero_context, 0)]:
        parser_client = MockLLMClient(deque([LLMResponse(content=QUERY, model="mock")]))
        answer_client = MockLLMClient(deque([LLMResponse(content=_answer(count), model="mock")]))
        decider = BranchingClient()
        agent = DynamicAgent(QueryParser(parser_client, "mock"), decider, Finalizer(answer_client, "mock"), "mock")
        answer = agent.run(ctx=ctx, question="What is the negative service rate?")
        assert answer.status == "ok"
        observed.append((len(decider.requests), [event.tool_name for event in answer.tool_trace if event.stage == "analysis_tool"]))
    assert observed == [(3, ["aggregate_aspects", "get_evidence"]), (2, ["aggregate_aspects"])]
