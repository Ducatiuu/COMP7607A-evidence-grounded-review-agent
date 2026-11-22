"""Append-only per-call telemetry for offline MOCK execution."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from src.llm_client import LLMClient, LLMRequest, LLMResponse


def _hash_json(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class RecordingLLMClient:
    """Wrap a MOCK client. Logs stay in an ignored local path and never imply live approval."""

    delegate: LLMClient
    output_path: Path
    run_id: str
    configured_model: str
    config_sha256: str
    method: Literal["a", "b", "c"] | None = None
    question_id: str | None = None
    repeat_index: int | None = None
    record_content: bool = False
    mode: Literal["MOCK"] = "MOCK"
    requests: int = field(default=0, init=False)

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        self.requests += 1
        timestamp = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        response = None
        failure = None
        try:
            response = self.delegate.complete_json(request)
            return response
        except Exception as exc:
            failure = type(exc).__name__
            raise
        finally:
            payload = request.payload
            row = {
                "mode": self.mode, "run_id": self.run_id, "config_sha256": self.config_sha256,
                "call_index": self.requests, "timestamp_utc": timestamp,
                "question_id": None if request.stage == "extract" else payload.get("question_id", self.question_id),
                "method": None if request.stage == "extract" else payload.get("method", self.method),
                "repeat_index": self.repeat_index, "record_id": payload.get("record_id") if request.stage == "extract" else None,
                "stage": request.stage,
                "schema_name": request.schema_name, "configured_model": self.configured_model,
                "response_model": response.model if response else None,
                "prompt_version": payload.get("prompt_version"),
                "prompt_sha256": hashlib.sha256(request.system_prompt.encode("utf-8")).hexdigest(),
                "request_sha256": _hash_json({"system_prompt": request.system_prompt, "payload": payload,
                                               "schema_name": request.schema_name}),
                "response_sha256": _hash_json(response.content) if response else None,
                "status": "failed" if failure else "ok", "error_type": failure,
                "latency_ms": (time.perf_counter() - started) * 1000,
                "input_tokens": response.input_tokens if response else None,
                "output_tokens": response.output_tokens if response else None,
                "cost_usd": None,
            }
            if self.record_content:
                row["request"] = {"system_prompt": request.system_prompt, "payload": payload}
                row["response"] = response.content if response else None
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with self.output_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
