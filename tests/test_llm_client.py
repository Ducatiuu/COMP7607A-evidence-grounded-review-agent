from collections import deque

import pytest

from src.llm_client import LLMRequest, LLMResponse, MockLLMClient


def test_mock_returns_explicit_fixtures_and_records_requests():
    expected = LLMResponse(content={"status": "ok"}, model="mock")
    client = MockLLMClient(responses=deque([expected, ValueError("offline failure")]))
    request = LLMRequest(stage="extract", system_prompt="Return JSON", payload={"text": "Nice food"}, schema_name="ExtractionResult")
    assert client.complete_json(request) == expected
    with pytest.raises(ValueError, match="offline failure"):
        client.complete_json(request)
    with pytest.raises(RuntimeError, match="no response fixture"):
        client.complete_json(request)
    assert client.requests == [request, request, request]
