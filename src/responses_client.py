"""OpenAI and DeepSeek Responses transport for the shared LLMClient boundary.

The adapter has no automatic retry. Callers own request and cost budgets.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.llm_client import LLMRequest, LLMResponse


_ENDPOINTS = {
    "openai": ("https://api.openai.com/v1/responses", "OPENAI_API_KEY"),
    "deepseek": ("https://api.deepseek.com/responses", "DEEPSEEK_API_KEY"),
}
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ProviderError(RuntimeError):
    """A sanitized provider or transport failure; never includes request content."""


def _post_json(body: dict[str, Any], api_key: str, timeout_seconds: float, endpoint: str) -> dict[str, Any]:
    request = Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise ProviderError(f"provider HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise ProviderError("provider transport failure") from None
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise ProviderError("provider response too large")
    try:
        result = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderError("provider returned invalid JSON") from None
    if not isinstance(result, dict):
        raise ProviderError("provider returned invalid response shape")
    return result


def _token_count(usage: object, name: str) -> int | None:
    if not isinstance(usage, dict):
        return None
    value = usage.get(name)
    return value if type(value) is int and value >= 0 else None


def _output_object(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("status") != "completed":
        raise ProviderError("provider response incomplete or failed")
    output = response.get("output")
    if not isinstance(output, list):
        raise ProviderError("provider output missing")
    messages = [item for item in output if isinstance(item, dict) and item.get("type") == "message"
                and item.get("role") == "assistant"]
    if len(messages) != 1 or messages[0].get("status") != "completed":
        raise ProviderError("provider assistant message missing or incomplete")
    content = messages[0].get("content")
    if not isinstance(content, list) or any(not isinstance(item, dict) for item in content):
        raise ProviderError("provider message content invalid")
    if any(item.get("type") == "refusal" for item in content):
        raise ProviderError("provider refused the request")
    text_parts = [item.get("text") for item in content if item.get("type") == "output_text"]
    if len(text_parts) != 1 or not isinstance(text_parts[0], str):
        raise ProviderError("provider JSON text missing")
    try:
        parsed = json.loads(text_parts[0])
    except json.JSONDecodeError:
        raise ProviderError("provider output is not JSON") from None
    if not isinstance(parsed, dict):
        raise ProviderError("provider output must be a JSON object")
    return parsed


@dataclass(frozen=True)
class ResponsesClient:
    """One synchronous request per call, with network use explicitly enabled."""

    provider: Literal["openai", "deepseek"]
    model: str
    max_output_tokens: int = 2048
    timeout_seconds: float = 60.0
    allow_network: bool = False
    post_json: Callable[[dict[str, Any], str, float, str], dict[str, Any]] = field(
        default=_post_json, repr=False, compare=False,
    )

    def __post_init__(self) -> None:
        if self.provider not in _ENDPOINTS:
            raise ValueError("unsupported provider")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("nonempty provider model required")
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 1:
            raise ValueError("positive max_output_tokens required")
        if type(self.timeout_seconds) not in (int, float) or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("positive finite timeout required")

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        if not self.allow_network:
            raise ProviderError("provider network use is disabled")
        endpoint, key_name = _ENDPOINTS[self.provider]
        api_key = os.environ.get(key_name)
        if not api_key or "\r" in api_key or "\n" in api_key:
            raise ProviderError(f"{key_name} is unavailable or invalid")
        body = {
            "model": self.model,
            "input": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": json.dumps({"schema_name": request.schema_name,
                                                       "payload": request.payload}, ensure_ascii=False)},
            ],
            "text": {"format": {"type": "json_object"}},
            "max_output_tokens": self.max_output_tokens,
        }
        if self.provider == "openai":
            body.update({"truncation": "disabled", "store": False})
        else:
            # DeepSeek Responses defaults to high-effort thinking. Keep bounded
            # JSON extraction and question answering in its non-thinking mode.
            body["reasoning"] = {"effort": "none"}
        started = time.perf_counter()
        response = self.post_json(body, api_key, self.timeout_seconds, endpoint)
        if response.get("model") != self.model:
            raise ProviderError("provider model identifier mismatch")
        return LLMResponse(
            content=_output_object(response), model=self.model,
            input_tokens=_token_count(response.get("usage"), "input_tokens"),
            output_tokens=_token_count(response.get("usage"), "output_tokens"),
            latency_ms=(time.perf_counter() - started) * 1000,
        )
