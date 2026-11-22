from collections import deque

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
