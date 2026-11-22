"""Aggregate local MOCK model-call telemetry without treating unknown usage as zero."""

from __future__ import annotations

import json
from collections import defaultdict
from math import ceil
from pathlib import Path
from statistics import median
from typing import Any, Literal

from pydantic import Field, model_validator

from src.schemas.models import StrictModel


class ModelCallRow(StrictModel):
    mode: Literal["MOCK"]
    run_id: str = Field(min_length=1)
    config_sha256: str = Field(min_length=64, max_length=64)
    call_index: int = Field(ge=1)
    timestamp_utc: str = Field(min_length=1)
    question_id: str | None
    method: Literal["a", "b", "c"] | None
    repeat_index: int | None = Field(ge=0)
    record_id: str | None
    stage: str = Field(min_length=1)
    schema_name: str = Field(min_length=1)
    configured_model: str = Field(min_length=1)
    response_model: str | None
    prompt_version: str | None
    prompt_sha256: str = Field(min_length=64, max_length=64)
    request_sha256: str = Field(min_length=64, max_length=64)
    response_sha256: str | None
    status: Literal["ok", "failed"]
    error_type: str | None
    latency_ms: float = Field(ge=0)
    input_tokens: int | None = Field(ge=0)
    output_tokens: int | None = Field(ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    request: dict[str, Any] | None = None
    response: dict[str, Any] | None = None

    @model_validator(mode="after")
    def aligned(self) -> "ModelCallRow":
        if (self.status == "failed") != (self.error_type is not None):
            raise ValueError("call status and error type disagree")
        if self.status == "failed" and (self.response_model is not None or self.response_sha256 is not None
                                        or self.input_tokens is not None or self.output_tokens is not None):
            raise ValueError("failed call cannot claim response usage")
        if self.stage == "extract" and (self.question_id is not None or self.method is not None or self.record_id is None):
            raise ValueError("extraction call attribution is inconsistent")
        if self.stage != "extract" and (self.question_id is None or self.method is None or self.repeat_index is None):
            raise ValueError("query call attribution is incomplete")
        return self


def _latency_stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "median_ms": None, "p95_ms": None}
    ordered = sorted(values)
    return {"count": len(values), "median_ms": median(ordered),
            "p95_ms": ordered[ceil(0.95 * len(ordered)) - 1]}


def summarize_model_calls(path: str | Path, *, config_sha256: str, method: str, task_keys: set[str],
                          answer_api_requests_known: int, answer_api_requests_unknown_rows: int) -> dict:
    """Use physical call rows; reconcile against answer rows only when their usage is complete."""
    path = Path(path)
    if not path.exists():
        return {"available": False, "reason": "model_calls.jsonl absent"}
    rows: list[ModelCallRow] = []
    next_index: dict[str, int] = defaultdict(lambda: 1)
    query_run_keys: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            row = ModelCallRow.model_validate_json(line)
        except Exception as exc:
            raise ValueError(f"invalid model call row {line_number}") from exc
        if row.config_sha256 != config_sha256:
            raise ValueError(f"model call {line_number} does not match run config")
        if row.call_index != next_index[row.run_id]:
            raise ValueError(f"nonconsecutive model call index at row {line_number}")
        next_index[row.run_id] += 1
        if row.stage != "extract":
            key = json.dumps([row.question_id, row.repeat_index], separators=(",", ":"))
            if row.method != method or key not in task_keys:
                raise ValueError(f"model call {line_number} does not match run task")
            if row.run_id in query_run_keys and query_run_keys[row.run_id] != key:
                raise ValueError(f"model call run ID spans multiple tasks at row {line_number}")
            query_run_keys[row.run_id] = key
        rows.append(row)

    stages = {}
    for stage in sorted({row.stage for row in rows}):
        selected = [row for row in rows if row.stage == stage]
        stages[stage] = {"requests": len(selected), "failed_requests": sum(row.status == "failed" for row in selected),
                         "call_latency_ms": _latency_stats([row.latency_ms for row in selected])}
    extraction = [row for row in rows if row.stage == "extract"]
    query = [row for row in rows if row.stage != "extract"]
    query_by_run: dict[str, float] = defaultdict(float)
    for row in query:
        query_by_run[row.run_id] += row.latency_ms
    answer_delta = (len(rows) - answer_api_requests_known) if answer_api_requests_unknown_rows == 0 else None
    return {
        "available": True, "call_rows": len(rows), "failed_call_rows": sum(row.status == "failed" for row in rows),
        "extraction_requests": len(extraction), "query_requests": len(query), "stages": stages,
        "extraction_call_latency_ms": _latency_stats([row.latency_ms for row in extraction]),
        "query_call_latency_ms": _latency_stats([row.latency_ms for row in query]),
        "query_model_latency_per_attempt_ms": _latency_stats(list(query_by_run.values())),
        "input_tokens_known": sum(row.input_tokens for row in rows if row.input_tokens is not None),
        "input_tokens_unknown_calls": sum(row.input_tokens is None for row in rows),
        "output_tokens_known": sum(row.output_tokens for row in rows if row.output_tokens is not None),
        "output_tokens_unknown_calls": sum(row.output_tokens is None for row in rows),
        "cost_usd": None if not rows or any(row.cost_usd is None for row in rows) else sum(row.cost_usd for row in rows),
        "physical_minus_answer_requests": answer_delta,
        "request_count_agrees": (answer_delta == 0) if answer_delta is not None else None,
    }
