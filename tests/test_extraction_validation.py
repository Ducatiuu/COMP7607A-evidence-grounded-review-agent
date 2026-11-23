from collections import deque
import json

import pytest

from src.absa_service import ExtractionService
from src.llm_client import LLMResponse, MockLLMClient
from src.schemas import Record, RecordSet


def _response(record_id, aspects):
    return LLMResponse(content={"record_id": record_id, "aspects": aspects, "status": "ok", "error": None}, model="mock")


def test_extract_retries_bad_span_and_aligns_ids():
    record = Record(record_id="R1", text="Tasty food.")
    client = MockLLMClient(deque([
        _response("R1", [{"category": "food", "sentiment": "positive", "evidence": ["tasty food"]}]),
        _response("R1", [{"category": "food", "sentiment": "positive", "evidence": ["Tasty food"]}]),
    ]))
    run = ExtractionService(client=client, provider_model="mock").extract(RecordSet(records=[record]))
    assert (run.requests, run.retries, run.cache_hits) == (2, 1, 0)
    assert run.dataset.extractions[0].aspects[0].evidence == ["Tasty food"]


def test_persistent_invalid_output_is_failed_not_empty_success():
    client = MockLLMClient(deque([_response("wrong", []), _response("R1", [{"category": "food", "sentiment": "positive", "evidence": ["invented"]}])]))
    run = ExtractionService(client=client, provider_model="mock").extract(RecordSet(records=[Record(record_id="R1", text="Tasty food.")]))
    assert run.dataset.coverage.failed_ids == ["R1"]
    assert run.dataset.extractions[0].status == "failed"
    assert run.requests == 2


def test_duplicate_category_and_invalid_label_use_one_retry():
    aspect = {"category": "food", "sentiment": "positive", "evidence": ["food"]}
    client = MockLLMClient(deque([
        _response("R1", [aspect, aspect]),
        _response("R1", [{"category": "food", "sentiment": "mixed", "evidence": ["food"]}]),
    ]))
    run = ExtractionService(client=client, provider_model="mock").extract(RecordSet(records=[Record(record_id="R1", text="food")]))
    assert run.dataset.extractions[0].status == "failed"
    assert len(client.requests) == 2


def test_one_result_per_record_with_failure_retained():
    records = RecordSet(records=[Record(record_id="A", text="good food"), Record(record_id="B", text="bad service")])
    client = MockLLMClient(deque([_response("A", [{"category": "food", "sentiment": "positive", "evidence": ["good food"]}]), TimeoutError(), TimeoutError()]))
    run = ExtractionService(client=client, provider_model="mock").extract(records)
    assert [r.record_id for r in run.dataset.extractions] == ["A", "B"]
    assert run.dataset.coverage.model_dump() == {"total": 2, "success": 1, "failed_ids": ["B"]}
    assert run.requests == 3


def test_mismatched_actual_model_is_failed_and_not_cached():
    record = Record(record_id="R1", text="food")
    client = MockLLMClient(deque([_response("R1", []), _response("R1", [])]))
    run = ExtractionService(client=client, provider_model="unexpected-model").extract(RecordSet(records=[record]))
    assert run.dataset.extractions[0].status == "failed"
    assert run.cache_hits == 0


def test_attempt_diagnostics_keep_only_safe_structure_and_categories():
    record = Record(record_id="R1", text="Tasty food.")
    client = MockLLMClient(deque([
        LLMResponse(content={"record_id": "R1", "status": "ok", "error": None,
                             "aspects": [], "SECRET_FIELD": "SECRET_MODEL_OUTPUT"}, model="mock"),
        _response("R1", [{"category": "food", "sentiment": "positive",
                          "evidence": ["SECRET_NOT_IN_SOURCE"]}]),
    ]))
    run = ExtractionService(client=client, provider_model="mock").extract(RecordSet(records=[record]))
    assert [item["category"] for item in run.attempt_diagnostics] == [
        "schema_validation", "evidence_mismatch"]
    assert run.attempt_diagnostics[0]["issues"][0]["path"] == "[unrecognized]"
    safe = json.dumps(run.attempt_diagnostics)
    assert "SECRET" not in safe and "Tasty food" not in safe


def test_transport_exception_message_is_never_copied_into_diagnostics():
    client = MockLLMClient(deque([TimeoutError("SECRET_KEY_VALUE"),
                                  TimeoutError("SECRET_REVIEW_TEXT")]))
    run = ExtractionService(client=client, provider_model="mock").extract(
        RecordSet(records=[Record(record_id="R1", text="Tasty food.")]))
    assert [item["category"] for item in run.attempt_diagnostics] == ["client_error", "client_error"]
    assert "SECRET" not in json.dumps(run.attempt_diagnostics)


def test_malformed_client_response_is_bounded_validation_failure():
    class BadClient:
        def complete_json(self, request):
            return {"SECRET_FIELD": "SECRET_MODEL_OUTPUT"}

    run = ExtractionService(client=BadClient(), provider_model="mock").extract(
        RecordSet(records=[Record(record_id="R1", text="Tasty food.")]))
    assert run.dataset.coverage.failed_ids == ["R1"]
    assert [item["category"] for item in run.attempt_diagnostics] == [
        "validation_error", "validation_error"]
    assert "SECRET" not in json.dumps(run.attempt_diagnostics)


def test_v2_prompt_explicitly_requires_evidence_array_without_relaxing_schema():
    record = Record(record_id="R1", text="Tasty food.")
    client = MockLLMClient(deque([
        _response("R1", [{"category": "food", "sentiment": "positive",
                          "evidence": "Tasty food"}]),
        _response("R1", [{"category": "food", "sentiment": "positive",
                          "evidence": ["Tasty food"]}]),
    ]))
    run = ExtractionService(client=client, provider_model="mock",
                            prompt_version="extract-v2").extract(RecordSet(records=[record]))
    assert run.requests == 2 and run.dataset.coverage.success == 1
    assert run.attempt_diagnostics[0]["category"] == "schema_validation"
    assert run.attempt_diagnostics[0]["issues"][0] == {
        "path": "aspects.[index].evidence", "type": "list_type"}
    assert all("evidence field MUST be a JSON array" in item.system_prompt
               and item.payload["prompt_version"] == "extract-v2" for item in client.requests)
    with pytest.raises(ValueError, match="unsupported extraction prompt"):
        ExtractionService(client=client, provider_model="mock", prompt_version="extract-v999")
