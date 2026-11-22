import json
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from src.absa_service import ExtractionService
from src.llm_client import LLMRequest
from src.responses_client import ResponsesClient, ProviderError, _post_json
from src.schemas import Record, RecordSet


def _response(content='{"status":"ok"}', *, status="completed", model="test-model", usage=None):
    return {
        "status": status, "model": model,
        "output": [{"type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": content}]}],
        "usage": usage,
    }


def _request():
    return LLMRequest(stage="extract", system_prompt="Return JSON", payload={"text": "Nice food"}, schema_name="ExtractionResult")


def test_network_disabled_and_missing_key_do_not_call_transport(monkeypatch):
    calls = []
    transport = lambda *args: calls.append(args)
    client = ResponsesClient("openai", "test-model", post_json=transport)
    with pytest.raises(ProviderError, match="disabled"):
        client.complete_json(_request())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = ResponsesClient("openai", "test-model", allow_network=True, post_json=transport)
    with pytest.raises(ProviderError, match="unavailable"):
        client.complete_json(_request())
    assert calls == []


def test_request_and_response_contract_without_network(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-do-not-use")
    calls = []

    def transport(body, key, timeout, endpoint):
        calls.append((body, key, timeout, endpoint))
        return _response(usage={"input_tokens": 12, "output_tokens": 7})

    client = ResponsesClient("openai", "test-model", max_output_tokens=256, timeout_seconds=5,
                             allow_network=True, post_json=transport)
    result = client.complete_json(_request())
    assert result.content == {"status": "ok"}
    assert (result.model, result.input_tokens, result.output_tokens) == ("test-model", 12, 7)
    assert result.latency_ms is not None and result.latency_ms >= 0
    assert len(calls) == 1
    body, key, timeout, endpoint = calls[0]
    assert key == "test-key-do-not-use" and timeout == 5
    assert endpoint == "https://api.openai.com/v1/responses"
    assert body["store"] is False and body["truncation"] == "disabled"
    assert body["max_output_tokens"] == 256
    assert body["text"] == {"format": {"type": "json_object"}}
    assert body["input"][0] == {"role": "system", "content": "Return JSON"}
    assert json.loads(body["input"][1]["content"]) == {
        "schema_name": "ExtractionResult", "payload": {"text": "Nice food"}}
    assert "test-key-do-not-use" not in repr(client)


@pytest.mark.parametrize("response, reason", [
    (_response(status="incomplete"), "incomplete"),
    (_response(model="different-model"), "model identifier"),
    (_response(content="not JSON"), "not JSON"),
    (_response(content="[]"), "JSON object"),
    ({**_response(), "output": [{"type": "message", "role": "assistant", "status": "completed",
                               "content": [{"type": "refusal", "refusal": "private"}]}]}, "refused"),
])
def test_provider_response_failures_are_rejected_without_retry(monkeypatch, response, reason):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-do-not-use")
    calls = []

    def transport(*args):
        calls.append(args)
        return response

    client = ResponsesClient("openai", "test-model", allow_network=True, post_json=transport)
    with pytest.raises(ProviderError, match=reason) as exc:
        client.complete_json(_request())
    assert "test-key-do-not-use" not in str(exc.value)
    assert len(calls) == 1


def test_unknown_or_invalid_usage_stays_unknown(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-do-not-use")
    client = ResponsesClient("openai", "test-model", allow_network=True,
                             post_json=lambda *_: _response(usage={"input_tokens": True, "output_tokens": -1}))
    result = client.complete_json(_request())
    assert result.input_tokens is None and result.output_tokens is None


def test_http_transport_sanitizes_provider_errors(monkeypatch):
    def http_error(*args, **kwargs):
        raise HTTPError("https://api.openai.com/v1/responses", 429, "secret error body", {}, BytesIO(b"secret"))

    monkeypatch.setattr("src.responses_client.urlopen", http_error)
    with pytest.raises(ProviderError, match="HTTP 429") as exc:
        _post_json({"model": "test-model"}, "test-key-do-not-use", 5, "https://api.openai.com/v1/responses")
    assert "secret" not in str(exc.value)

    monkeypatch.setattr("src.responses_client.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(URLError("private URL")))
    with pytest.raises(ProviderError, match="transport failure") as exc:
        _post_json({"model": "test-model"}, "test-key-do-not-use", 5, "https://api.openai.com/v1/responses")
    assert "private" not in str(exc.value)


@pytest.mark.parametrize("kwargs", [{"provider": "openai", "model": " "},
                                    {"provider": "openai", "model": "test-model", "max_output_tokens": 0},
                                    {"provider": "openai", "model": "test-model", "timeout_seconds": float("inf")},
                                    {"provider": "unknown", "model": "test-model"}])
def test_invalid_client_config_rejected(kwargs):
    with pytest.raises(ValueError):
        ResponsesClient(**kwargs)


def test_deepseek_uses_its_endpoint_and_key_without_unsupported_parameters(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    calls = []

    def transport(body, key, timeout, endpoint):
        calls.append((body, key, endpoint))
        return _response(model="deepseek-flash")

    client = ResponsesClient("deepseek", "deepseek-flash", allow_network=True, post_json=transport)
    assert client.complete_json(_request()).content == {"status": "ok"}
    body, key, endpoint = calls[0]
    assert endpoint == "https://api.deepseek.com/responses" and key == "deepseek-test-key"
    assert "store" not in body and "truncation" not in body


def test_responses_client_feeds_actual_extraction_contract(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-do-not-use")
    model_output = {"record_id": "R1", "aspects": [{"category": "food", "sentiment": "positive",
                                                    "evidence": ["Tasty food"]}], "status": "ok", "error": None}
    client = ResponsesClient("openai", "test-model", allow_network=True,
                             post_json=lambda *_: _response(content=json.dumps(model_output)))
    run = ExtractionService(client=client, provider_model="test-model").extract(
        RecordSet(records=[Record(record_id="R1", text="Tasty food.")]))
    assert (run.requests, run.retries, run.dataset.coverage.success) == (1, 0, 1)
    assert run.dataset.extractions[0].aspects[0].evidence == ["Tasty food"]
