"""One offline-injectable model boundary; no provider is contacted here."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class LLMRequest:
    stage: str
    system_prompt: str
    payload: dict[str, Any]
    schema_name: str


@dataclass(frozen=True)
class LLMResponse:
    content: dict[str, Any]
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None


class LLMClient(Protocol):
    def complete_json(self, request: LLMRequest) -> LLMResponse: ...


@dataclass
class MockLLMClient:
    """Consumes explicit fixture responses and retains requests for assertions."""

    responses: deque[LLMResponse | Exception] = field(default_factory=deque)
    requests: list[LLMRequest] = field(default_factory=list)

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self.responses:
            raise RuntimeError("MockLLMClient has no response fixture")
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response
