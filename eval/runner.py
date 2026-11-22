"""Config-bound, append-only offline run ledger with explicit failure retention."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import Field, model_validator

from src.schemas import AnswerPayload
from src.schemas.models import StrictModel


class RunTask(StrictModel):
    question_id: str = Field(min_length=1)
    pack_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    repeat_index: int = Field(default=0, ge=0)

    @property
    def key(self) -> str:
        return json.dumps([self.question_id, self.repeat_index], separators=(",", ":"))


class RunConfig(StrictModel):
    method: Literal["a", "b", "c"]
    split: str = Field(min_length=1)
    condition: Literal["main", "repeats", "gold", "ablation", "challenge"] = "main"
    dataset_sha256: str = Field(min_length=64, max_length=64)
    question_manifest_sha256: str = Field(min_length=64, max_length=64)
    model_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    mock: bool = True
    max_api_requests: int | None = Field(default=None, ge=1)
    estimated_requests_per_task: int | None = Field(default=None, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)
    estimated_cost_per_task_usd: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def safe_mode_and_budget(self) -> "RunConfig":
        if not self.mock:
            raise ValueError("live execution is not configured or approved")
        if self.max_api_requests is not None and self.estimated_requests_per_task is None:
            raise ValueError("request cap needs conservative per-task estimate")
        if self.max_cost_usd is not None and self.estimated_cost_per_task_usd is None:
            raise ValueError("cost cap needs conservative per-task estimate")
        return self

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RunRow(StrictModel):
    key: str
    question_id: str
    pack_id: str
    repeat_index: int
    method: Literal["a", "b", "c"]
    condition: str
    mode: Literal["MOCK"] = "MOCK"
    config_sha256: str
    attempt_index: int = Field(ge=1)
    timestamp_utc: str
    latency_ms: float = Field(ge=0)
    status: Literal["ok", "partial", "insufficient_info", "clarification", "failed"]
    api_requests: int | None = Field(default=None, ge=0)
    cost_usd: float | None = None
    answer: AnswerPayload

    @model_validator(mode="after")
    def aligned(self) -> "RunRow":
        if (self.key != json.dumps([self.question_id, self.repeat_index], separators=(",", ":"))
                or self.answer.question_id != self.question_id or self.answer.method != self.method
                or self.answer.status != self.status):
            raise ValueError("run row fields are inconsistent")
        usage_requests = self.answer.usage.get("api_requests")
        if isinstance(usage_requests, int) and self.api_requests != usage_requests:
            raise ValueError("run row request usage is inconsistent")
        return self


class RunManifest(StrictModel):
    config: RunConfig
    config_sha256: str
    tasks_sha256: str
    task_keys: list[str]
    status: Literal["MOCK"] = "MOCK"

    @model_validator(mode="after")
    def aligned(self) -> "RunManifest":
        if self.config_sha256 != self.config.fingerprint or len(self.task_keys) != len(set(self.task_keys)):
            raise ValueError("manifest hash or task keys are inconsistent")
        return self


class RunSummary(StrictModel):
    config_sha256: str
    recorded: int
    skipped_existing: int
    retained_failures: int
    pending: int
    budget_stopped: bool


def _load_rows(path: Path, config: RunConfig, task_keys: set[str]) -> dict[str, list[RunRow]]:
    rows: dict[str, list[RunRow]] = {}
    if not path.exists():
        return rows
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            row = RunRow.model_validate_json(line)
        except Exception as exc:
            raise ValueError(f"invalid JSONL row {line_number}") from exc
        if row.config_sha256 != config.fingerprint or row.key not in task_keys or row.method != config.method or row.condition != config.condition:
            raise ValueError(f"run row {line_number} does not match manifest/config")
        attempts = rows.setdefault(row.key, [])
        if row.attempt_index != len(attempts) + 1:
            raise ValueError(f"nonconsecutive or duplicate attempt for {row.key}")
        attempts.append(row)
    return rows


def run_tasks(config: RunConfig, tasks: list[RunTask], output_dir: str | Path,
              execute: Callable[[RunTask], AnswerPayload], *, retry_failed: bool = False) -> RunSummary:
    keys = [task.key for task in tasks]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate task key")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    rows_path = output_dir / "answers.jsonl"
    tasks_json = json.dumps([task.model_dump(mode="json") for task in tasks], sort_keys=True, separators=(",", ":"))
    tasks_sha256 = hashlib.sha256(tasks_json.encode("utf-8")).hexdigest()
    expected_manifest = RunManifest(config=config, config_sha256=config.fingerprint, tasks_sha256=tasks_sha256, task_keys=keys)
    if manifest_path.exists():
        actual = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if actual != expected_manifest:
            raise ValueError("resume manifest/config/task list mismatch")
    else:
        if rows_path.exists():
            raise ValueError("answers exist without a manifest")
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(expected_manifest.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(manifest_path)
    existing = _load_rows(rows_path, config, set(keys))
    if config.max_api_requests is not None and any(row.api_requests is None for attempts in existing.values() for row in attempts):
        raise ValueError("cannot safely resume request cap with unknown prior usage")
    requests_spent = sum(row.api_requests for attempts in existing.values() for row in attempts if row.api_requests is not None)
    attempts_spent = sum(len(attempts) for attempts in existing.values())
    recorded = skipped_existing = retained_failures = pending = 0
    budget_stopped = False

    def needs_attempt(task: RunTask) -> bool:
        previous = existing.get(task.key, [])
        return not previous or (retry_failed and previous[-1].status in {"failed", "partial"} and len(previous) < 2)

    for index, task in enumerate(tasks):
        attempts = existing.get(task.key, [])
        if attempts and attempts[-1].status in {"ok", "insufficient_info", "clarification"}:
            skipped_existing += 1
            continue
        if attempts and (not retry_failed or len(attempts) >= 2):
            retained_failures += 1
            continue
        if config.max_api_requests is not None and requests_spent + config.estimated_requests_per_task > config.max_api_requests:
            budget_stopped = True
            pending += sum(1 for rest in tasks[index:] if needs_attempt(rest))
            break
        if config.max_cost_usd is not None and (attempts_spent + 1) * config.estimated_cost_per_task_usd > config.max_cost_usd:
            budget_stopped = True
            pending += sum(1 for rest in tasks[index:] if needs_attempt(rest))
            break
        started = time.perf_counter()
        try:
            answer = execute(task)
            if answer.question_id != task.question_id or answer.method != config.method:
                raise ValueError("executor returned mismatched question or method")
        except Exception:
            answer = AnswerPayload(method=config.method, question_id=task.question_id, status="failed", answer_text="", error_code="runner_execution_error")
        api_requests = answer.usage.get("api_requests")
        if not isinstance(api_requests, int) or api_requests < 0:
            api_requests = None
        row = RunRow(
            key=task.key, question_id=task.question_id, pack_id=task.pack_id,
            repeat_index=task.repeat_index, method=config.method, condition=config.condition,
            config_sha256=config.fingerprint, attempt_index=len(attempts) + 1,
            timestamp_utc=datetime.now(timezone.utc).isoformat(), latency_ms=(time.perf_counter() - started) * 1000,
            status=answer.status, api_requests=api_requests, answer=answer,
        )
        with rows_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(row.model_dump_json() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        existing.setdefault(task.key, []).append(row)
        recorded += 1
        attempts_spent += 1
        if api_requests is not None:
            requests_spent += api_requests
    return RunSummary(config_sha256=config.fingerprint, recorded=recorded, skipped_existing=skipped_existing,
                      retained_failures=retained_failures, pending=pending, budget_stopped=budget_stopped)
