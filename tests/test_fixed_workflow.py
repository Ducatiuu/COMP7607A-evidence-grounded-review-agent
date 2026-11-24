from collections import deque

from src.controllers import FixedWorkflow, QueryParser
from src.llm_client import LLMResponse, MockLLMClient
from src.verification import Finalizer
from test_tools import _dataset


def _workflow(query, answer=None):
    responses = [LLMResponse(content=query, model="mock")]
    if answer is not None:
        responses.append(LLMResponse(content=answer, model="mock"))
    client = MockLLMClient(deque(responses))
    return FixedWorkflow(QueryParser(client, "mock"), Finalizer(client, "mock")), client


def test_fixed_rate_uses_one_aggregate_and_verified_claim():
    query = {"task_type": "rate", "categories": ["service"], "metric": "negative_rate", "denominator_spec": "aspect_mentions"}
    answer_data = {"status": "ok", "answer_text": "Two of three service mentions are negative.",
                   "numeric_claims": [{"metric": "negative_rate", "category": "service", "scope_ids": ["R01", "R02", "R03", "R04"], "value": 2 / 3, "numerator": 2, "denominator": 3}],
                   "denominator_explanation": "Three records mention service."}
    workflow, client = _workflow(query, answer_data)
    answer = workflow.run(ctx=_dataset(), question="What share of service mentions is negative?", question_id="Q-rate")
    assert answer.status == "ok" and answer.numeric_claims[0].value == 2 / 3
    assert [event.tool_name for event in answer.tool_trace] == ["aggregate_aspects"]
    assert answer.tool_trace[0].result_summary["stats"][0]["denominator"] == 3
    assert answer.usage["api_requests"] == 2 and answer.usage["analysis_tool_calls"] == 1
    assert [request.stage for request in client.requests] == ["query_parse", "answer"]


def test_fixed_rate_independent_subgroup_keeps_full_denominator():
    query = {"task_type": "rate", "categories": ["service"], "metric": "negative_rate",
             "denominator_spec": "aspect_mentions",
             "conditions": [{"category": "food", "sentiment": "positive"}]}
    claim = {"metric": "negative_rate", "category": "service", "scope_ids": ["R01", "R03"],
             "value": 0.5, "numerator": 1, "denominator": 2, "unit": "fraction"}
    answer_data = {"status": "ok", "answer_text": "One of two scoped reviews mentioning service is negative.",
                   "numeric_claims": [claim], "denominator_explanation": "Two scoped records mention service."}
    workflow, client = _workflow(query, answer_data)
    workflow.parser.prompt_version = "query-v4"
    workflow.finalizer.prompt_version = "answer-v6"
    answer = workflow.run(ctx=_dataset(), question="Among food-positive reviews, what fraction mention negative service?")
    assert answer.status == "ok" and answer.numeric_claims[0].denominator == 2
    assert [event.tool_name for event in answer.tool_trace] == ["filter_records", "aggregate_aspects"]
    assert answer.tool_trace[1].result_summary["stats"][0]["numerator"] == 1
    assert answer.tool_trace[1].result_summary["stats"][0]["denominator"] == 2
    assert client.requests[-1].payload["rate_definition"]["count_unit"] == "distinct_review_records"


def test_fixed_rate_target_negative_prefilter_fails_before_tools():
    query = {"task_type": "rate", "categories": ["service"], "metric": "negative_rate",
             "denominator_spec": "aspect_mentions",
             "conditions": [{"category": "service", "sentiment": "negative"}]}
    workflow, client = _workflow(query)
    workflow.parser.prompt_version = "query-v4"
    answer = workflow.run(ctx=_dataset(), question="What fraction of service mentions is negative?")
    assert answer.status == "failed" and answer.tool_trace == []
    assert answer.usage["api_requests"] == 1
    assert answer.usage["diagnostic"]["issues"][0]["coherence_rule"] == "rate_target_negative_filter"
    assert len(client.requests) == 1


def test_fixed_selection_filters_then_gets_evidence():
    query = {"task_type": "selection", "operator": "AND", "conditions": [{"category": "food", "sentiment": "positive"}, {"category": "service", "sentiment": "negative"}], "needs_evidence": True}
    answer_data = {"status": "ok", "answer_text": "R01 matches.", "selected_record_ids": ["R01"],
                   "citations": [{"record_id": "R01", "quote": "service was slow", "category": "service", "sentiment": "negative"}]}
    workflow, _ = _workflow(query, answer_data)
    answer = workflow.run(ctx=_dataset(), question="Which reviews praise food but criticize service?")
    assert answer.status == "ok" and answer.selected_record_ids == ["R01"]
    assert [event.tool_name for event in answer.tool_trace] == ["filter_records", "get_evidence"]


def test_fixed_missing_metadata_refuses_without_tools_or_answer_call():
    query = {"task_type": "rate", "categories": ["food"], "metric": "negative_rate", "denominator_spec": "all_records", "metadata_required": ["date"]}
    workflow, client = _workflow(query)
    answer = workflow.run(ctx=_dataset(), question="How did food complaints change by month?")
    assert answer.status == "insufficient_info" and answer.tool_trace == []
    assert len(client.requests) == 1


def test_fixed_comparison_preserves_tie_group():
    query = {"task_type": "comparison", "categories": ["service", "food"], "metric": "mention_count"}
    answer_data = {"status": "ok", "answer_text": "Food and service are tied.", "comparison_groups": [["service", "food"]],
                   "numeric_claims": [{"metric": "mention_count", "category": category, "scope_ids": ["R01", "R02", "R03", "R04"], "value": 3} for category in ["service", "food"]]}
    workflow, _ = _workflow(query, answer_data)
    answer = workflow.run(ctx=_dataset(), question="Which has more mentions, food or service?")
    assert answer.status == "ok"
    assert [[c.value for c in group] for group in answer.comparison_groups] == [["service", "food"]]


def test_fixed_rejects_wrong_numeric_answer_after_one_repair():
    query = {"task_type": "count", "categories": ["service"], "metric": "negative_count"}
    bad = {"status": "ok", "answer_text": "Three complaints", "numeric_claims": [{"metric": "negative_count", "category": "service", "scope_ids": ["R01", "R02", "R03", "R04"], "value": 3}]}
    client = MockLLMClient(deque([LLMResponse(content=query, model="mock"), LLMResponse(content=bad, model="mock"), LLMResponse(content=bad, model="mock")]))
    workflow = FixedWorkflow(QueryParser(client, "mock"), Finalizer(client, "mock"))
    answer = workflow.run(ctx=_dataset(), question="How many service complaints?")
    assert answer.status == "failed" and answer.error_code == "answer_verification_failed"
    assert answer.usage["api_requests"] == 3
