from collections import deque

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
    assert [r["record_id"] for r in request.payload["records"]] == ["R01", "R02", "R03", "R04"]
    assert "extractions" not in request.payload and "query" not in request.payload and "tools" not in request.payload


def test_direct_invalid_output_is_failure_without_tool_repair():
    client = MockLLMClient(deque([LLMResponse(content={"status": "ok", "answer_text": "bad", "numeric_claims": [{"metric": "x", "value": "many"}]}, model="mock")]))
    answer = DirectLLM(client, "mock").run(records=RecordSet(records=_dataset().dataset.records), question="How many?")
    assert answer.status == "failed" and answer.error_code == "invalid_direct_answer"
    assert len(client.requests) == 1
