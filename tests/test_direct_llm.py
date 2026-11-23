from collections import deque
import json

import pytest

from src.controllers import DirectLLM
from src.llm_client import LLMResponse, MockLLMClient
from src.schemas import RecordSet
from test_tools import _dataset


def test_direct_method_receives_complete_raw_pack_only():
    records = RecordSet(records=_dataset().dataset.records)
    client = MockLLMClient(deque([LLMResponse(content={"method": "a", "status": "ok", "answer_text": "2 service complaints", "numeric_claims": [{"metric": "negative_count", "category": "service", "value": 2}], "tool_trace": []}, model="mock")]))
    answer = DirectLLM(client, "mock").run(records=records, question="How many service complaints?", question_id="Q1")
    assert answer.status == "ok" and answer.method == "a" and answer.tool_trace == []
    request = client.requests[0]
    assert request.stage == "direct_answer"
    assert request.payload["prompt_version"] == "direct-v2"
    assert '"answer_text"' in request.system_prompt and '"numeric_claims"' in request.system_prompt
    assert [r["record_id"] for r in request.payload["records"]] == ["R01", "R02", "R03", "R04"]
    assert "extractions" not in request.payload and "query" not in request.payload and "tools" not in request.payload


def test_direct_v3_comparison_shape_is_explicit():
    records = RecordSet(records=_dataset().dataset.records)
    client = MockLLMClient(deque([LLMResponse(content={
        "status": "ok", "answer_text": "Food and service tie.",
        "comparison_groups": [["food", "service"], ["price"]]}, model="mock")]))
    answer = DirectLLM(client, "mock", prompt_version="direct-v3").run(
        records=records, question="Compare categories")
    assert answer.status == "ok"
    assert client.requests[0].payload["prompt_version"] == "direct-v3"
    assert '[["food","service"],["price"]]' in client.requests[0].system_prompt
    with pytest.raises(ValueError, match="unsupported direct prompt version"):
        DirectLLM(client, "mock", prompt_version="direct-unknown")


def test_direct_invalid_output_is_failure_without_tool_repair():
    client = MockLLMClient(deque([LLMResponse(content={"status": "ok", "answer_text": "bad", "numeric_claims": [{"metric": "x", "value": "many"}], "private model key": "secret review text"}, model="mock", input_tokens=12, output_tokens=7)]))
    answer = DirectLLM(client, "mock").run(records=RecordSet(records=_dataset().dataset.records), question="How many?")
    assert answer.status == "failed" and answer.error_code == "invalid_direct_answer"
    assert answer.usage["input_tokens"] == 12 and answer.usage["output_tokens"] == 7
    diagnostic = answer.usage["diagnostic"]
    assert diagnostic["stage"] == "schema_validation" and diagnostic["issue_count"] >= 2
    assert {issue["type"] for issue in diagnostic["issues"]} >= {"extra_forbidden"}
    assert "secret review text" not in json.dumps(answer.model_dump())
    assert "private model key" not in json.dumps(answer.model_dump())
    assert len(client.requests) == 1


def test_direct_transport_error_is_sanitized_and_not_retried():
    client = MockLLMClient(deque([RuntimeError("private provider response and key")]))
    answer = DirectLLM(client, "mock").run(
        records=RecordSet(records=_dataset().dataset.records), question="How many?")
    assert answer.status == "failed" and answer.usage["diagnostic"] == {"stage": "model_request"}
    assert answer.usage["input_tokens"] is None and answer.usage["output_tokens"] is None
    assert "private" not in json.dumps(answer.model_dump())
    assert len(client.requests) == 1


def test_direct_model_mismatch_preserves_known_usage_without_model_text():
    client = MockLLMClient(deque([LLMResponse(content={"status": "ok", "answer_text": "x"},
                                               model="other-model", input_tokens=3, output_tokens=4)]))
    answer = DirectLLM(client, "expected-model").run(
        records=RecordSet(records=_dataset().dataset.records), question="How many?")
    assert answer.usage["diagnostic"] == {"stage": "model_mismatch"}
    assert (answer.usage["input_tokens"], answer.usage["output_tokens"]) == (3, 4)
    assert "other-model" not in json.dumps(answer.model_dump())
