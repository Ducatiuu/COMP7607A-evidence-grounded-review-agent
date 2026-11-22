from collections import deque

from src.absa_service import ExtractionCache, ExtractionService
from src.llm_client import LLMResponse, MockLLMClient
from src.schemas import Record, RecordSet


def _client(model="mock"):
    return MockLLMClient(deque([LLMResponse(content={"record_id": "R1", "aspects": [{"category": "food", "sentiment": "positive", "evidence": ["Good food"]}], "status": "ok", "error": None}, model=model)]))


def test_same_text_different_id_rebinds_cache_without_new_request(tmp_path):
    cache = ExtractionCache(directory=tmp_path)
    client = _client("mock-v1")
    service = ExtractionService(client=client, provider_model="mock-v1", cache=cache)
    first = service.extract(RecordSet(records=[Record(record_id="R1", text="Good food")]))
    second = service.extract(RecordSet(records=[Record(record_id="R2", text="Good food")]))
    assert first.requests == 1
    assert (second.requests, second.cache_hits) == (0, 1)
    assert second.dataset.extractions[0].record_id == "R2"
    assert "R1" not in next(tmp_path.iterdir()).read_text(encoding="utf-8")


def test_version_or_config_change_is_cache_miss(tmp_path):
    cache = ExtractionCache(directory=tmp_path)
    ExtractionService(client=_client("mock-v1"), provider_model="mock-v1", cache=cache).extract(RecordSet(records=[Record(record_id="R1", text="Good food")]))
    for kwargs in [
        {"provider_model": "mock-v2"},
        {"provider_model": "mock-v1", "prompt_version": "extract-v2"},
        {"provider_model": "mock-v1", "schema_version": "v2"},
        {"provider_model": "mock-v1", "extraction_config": {"temperature": 0.1}},
    ]:
        run = ExtractionService(client=_client(kwargs["provider_model"]), cache=cache, **kwargs).extract(RecordSet(records=[Record(record_id="R1", text="Good food")]))
        assert (run.requests, run.cache_hits) == (1, 0)


def test_corrupt_cache_entry_is_recomputed(tmp_path):
    cache = ExtractionCache(directory=tmp_path)
    key = cache.key(text="Good food", provider_model="mock", prompt_version="extract-v1", schema_version="v1", extraction_config={})
    (tmp_path / f"{key}.json").write_text('{"aspects":[{"category":"food","sentiment":"positive","evidence":["not in text"]}]}', encoding="utf-8")
    run = ExtractionService(client=_client(), provider_model="mock", cache=cache).extract(RecordSet(records=[Record(record_id="R1", text="Good food")]))
    assert (run.requests, run.cache_hits) == (1, 0)
