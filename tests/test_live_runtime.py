from collections import deque

import pytest

from src.live_cost import CostLimitedClient, plan_cost
from src.live_runtime import RequestLimitedClient, RequestLimitError, run_model_method
from src.llm_client import LLMRequest, LLMResponse, MockLLMClient
from src.schemas import Record, RecordSet


def _records():
    return RecordSet(records=[Record(record_id="R1", text="The service was slow."),
                              Record(record_id="R2", text="Quick service.")])


def _reply(content):
    return LLMResponse(content=content, model="model-one", input_tokens=10, output_tokens=5)


def _extraction_responses():
    return [_reply({"record_id": "R1", "status": "ok", "error": None,
                    "aspects": [{"category": "service", "sentiment": "negative", "evidence": ["service was slow"]}]}),
            _reply({"record_id": "R2", "status": "ok", "error": None,
                    "aspects": [{"category": "service", "sentiment": "positive", "evidence": ["Quick service"]}]})]


def _query():
    return _reply({"task_type": "count", "categories": ["service"], "metric": "negative_count"})


def _answer():
    return _reply({"status": "ok", "answer_text": "One review mentions negative service.",
                   "numeric_claims": [{"metric": "negative_count", "category": "service",
                                       "scope_ids": ["R1", "R2"], "value": 1}]})


def _run(method, client, *, extraction_dataset=None, max_api_requests=None, records=None):
    records = records or _records()
    return run_model_method(records, method=method, question="How many reviews mention negative service?",
                            client=client, model_id="model-one", max_api_requests=max_api_requests or 20,
                            max_records=10, max_input_chars=1000, extraction_dataset=extraction_dataset)


def test_direct_method_uses_raw_records_without_extraction():
    client = MockLLMClient(deque([_reply({"status": "ok", "answer_text": "One review has negative service."})]))
    result = _run("a", client, max_api_requests=1)
    assert result.answer.status == "ok" and result.requests == 1
    assert (result.input_tokens, result.output_tokens) == (10, 5)
    assert result.extraction_dataset is None and result.extraction_requests == 0
    assert client.requests[0].stage == "direct_answer"
    assert len(client.requests[0].payload["records"]) == 2


def test_b_and_c_share_real_extraction_contract_without_canned_dataset():
    b_client = MockLLMClient(deque([*_extraction_responses(), _query(), _answer()]))
    b = _run("b", b_client, max_api_requests=7)
    assert b.answer.status == "ok" and b.answer.numeric_claims[0].value == 1
    assert (b.requests, b.extraction_requests, b.answer.usage["api_requests"]) == (4, 2, 4)
    assert (b.input_tokens, b.output_tokens) == (40, 20)
    assert [item.stage for item in b_client.requests] == ["extract", "extract", "query_parse", "answer"]

    c_client = MockLLMClient(deque([
        _query(),
        _reply({"action": "call_tools", "calls": [{"name": "aggregate_aspects",
                                                   "arguments": {"categories": ["service"], "metric": "negative_count"}}]}),
        _reply({"action": "finish", "calls": []}), _answer(),
    ]))
    c = _run("c", c_client, extraction_dataset=b.extraction_dataset, max_api_requests=7)
    assert c.answer.status == "ok" and c.answer.numeric_claims[0].value == 1
    assert (c.requests, c.extraction_requests) == (4, 0)
    assert [item.stage for item in c_client.requests] == ["query_parse", "dynamic_decision", "dynamic_decision", "answer"]
    assert c.dataset_sha256 == b.dataset_sha256


def test_request_and_source_limits_fail_before_model_use():
    client = MockLLMClient()
    with pytest.raises(ValueError, match="conservative"):
        _run("b", client, max_api_requests=6)
    with pytest.raises(ValueError, match="record count"):
        run_model_method(_records(), method="a", question="Count", client=client, model_id="model-one",
                         max_api_requests=1, max_records=1, max_input_chars=1000)
    with pytest.raises(ValueError, match="character limit"):
        run_model_method(_records(), method="a", question="Count", client=client, model_id="model-one",
                         max_api_requests=1, max_records=10, max_input_chars=5)
    assert client.requests == []


def test_mismatched_shared_extraction_rejected_before_model_use():
    b = _run("b", MockLLMClient(deque([*_extraction_responses(), _query(), _answer()])))
    client = MockLLMClient()
    other = RecordSet(records=[Record(record_id="R1", text="Different service.")])
    with pytest.raises(ValueError, match="does not match"):
        _run("c", client, extraction_dataset=b.extraction_dataset, records=other)
    with pytest.raises(ValueError, match="Method A"):
        _run("a", client, extraction_dataset=b.extraction_dataset)
    assert client.requests == []


def test_request_limiter_counts_failed_attempt_and_stops_next_request():
    client = MockLLMClient(deque([TimeoutError("offline transport error")]))
    limited = RequestLimitedClient(client, max_requests=1)
    request = LLMRequest(stage="extract", system_prompt="JSON", payload={}, schema_name="ExtractionResult")
    with pytest.raises(TimeoutError):
        limited.complete_json(request)
    with pytest.raises(RequestLimitError):
        limited.complete_json(request)
    assert limited.requests == 1 and len(client.requests) == 1


def test_invalid_or_missing_token_usage_remains_unknown():
    client = MockLLMClient(deque([LLMResponse(content={}, model="model-one", input_tokens=True, output_tokens=-1)]))
    limited = RequestLimitedClient(client, max_requests=1)
    limited.complete_json(LLMRequest(stage="query_parse", system_prompt="JSON", payload={}, schema_name="QuerySpec"))
    assert limited.input_tokens is None and limited.output_tokens is None


def test_cost_gate_freezes_real_requests_after_transport_failure():
    records = RecordSet(records=[Record(record_id="R1", text="Slow service.")])
    plan = plan_cost(max_requests=5, max_input_tokens_per_request=1000,
                     max_output_tokens_per_request=1000, input_usd_per_million="1",
                     output_usd_per_million="2", max_cost_usd="0.015",
                     price_source="fixture://not-a-quote", price_date="2026-11-22")
    delegate = MockLLMClient(deque([TimeoutError("offline failure")]))
    guarded = CostLimitedClient(delegate, plan)
    result = run_model_method(records, method="b", question="Count negative service reviews",
                              client=guarded, model_id="model-one", max_api_requests=5,
                              max_records=1, max_input_chars=100)
    assert result.answer.status == "failed"
    assert result.requests == guarded.requests == len(delegate.requests) == 1
    assert result.input_tokens is None and guarded.estimated_cost_usd is None
