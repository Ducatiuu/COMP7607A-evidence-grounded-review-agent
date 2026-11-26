"""Hash-bound formal A/B/C runner. Importing and dry-running never contact a provider.

The entry point rebuilds Stage 1 preflight from current files before allowing a
run. Gold and reference paths are used only by preflight, never by the model loop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from eval.questions import QuestionCandidate
from scripts.plan_final_formal_experiment import build_final_plan
from scripts.plan_formal_experiment import build_plan
from scripts.run_dev_pilot import _append_json, _durable_json, _GuardProxy
from src.absa_service import ExtractionService
from src.data_loader import dataset_fingerprint, load_csv
from src.deepseek_balance import BalanceError, require_dev_run_balance
from src.live_cost import BudgetError, CostLimitedClient, plan_cost
from src.live_runtime import conservative_request_bound, run_model_method
from src.llm_client import LLMClient, LLMRequest, LLMResponse
from src.responses_client import ResponsesClient
from src.schemas import ExtractionDataset, RecordSet
from src.semeval import CandidateSplit


@dataclass(frozen=True)
class FormalInputs:
    lock_path: Path
    split_path: Path
    test_csv: Path
    dev_csv: Path
    questions_path: Path
    references_path: Path
    test_gold_path: Path
    metrics_path: Path
    reviewer_1_path: Path
    reviewer_2_path: Path
    release_path: Path | None = None
    adjudication_path: Path | None = None


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_sha(value: object) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        raise ValueError("truncated run journal; manual inspection required")
    rows = [json.loads(line) for line in data.splitlines()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("invalid run journal row")
    return rows


def checked_plan(plan_path: Path, inputs: FormalInputs, *, resume: bool = False) -> dict:
    """Recompute all review, release, source and price-bound checks from disk."""
    saved = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(saved, dict):
        raise ValueError("formal plan must be an object")
    try:
        lock = json.loads(inputs.lock_path.read_text(encoding="utf-8"))
        builder = build_final_plan if lock.get("schema_version") == 2 else build_plan
        fresh = builder(
            lock_path=inputs.lock_path, split_path=inputs.split_path,
            test_csv=inputs.test_csv, dev_csv=inputs.dev_csv,
            questions_path=inputs.questions_path, references_path=inputs.references_path,
            test_gold_path=inputs.test_gold_path, metrics_path=inputs.metrics_path,
            reviewer_1_path=inputs.reviewer_1_path, reviewer_2_path=inputs.reviewer_2_path,
            release_path=inputs.release_path, adjudication_path=inputs.adjudication_path,
            run_dir=Path(saved["planned_run_directory"]), provider=saved["provider"],
            model=saved["model"], max_input_chars=saved["max_input_chars"],
            max_input_tokens=saved["max_input_tokens_per_request"],
            max_output_tokens=saved["max_output_tokens_per_request"],
            max_api_requests=saved["max_api_requests"],
            max_cost_usd=saved["max_cost_usd"],
            input_usd_per_million=saved["input_usd_per_million"],
            output_usd_per_million=saved["output_usd_per_million"],
            price_source=saved["price_source"], price_date=saved["price_date"],
            timeout_seconds=saved["timeout_seconds"],
            allow_existing_run_dir=resume,
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("formal plan is missing required fields") from exc
    if saved != fresh or saved.get("plan_sha256") != fresh["plan_sha256"]:
        raise ValueError("saved formal plan differs from current inputs or configuration")
    if (fresh["status"] != "FROZEN_PREFLIGHT_READY"
            or fresh["material_state"] != "FROZEN"
            or fresh["question_review_state"] != "REVIEWED_AWAITING_ADJUDICATION_AND_FREEZE"
            or not fresh["material_gate_passed"] or not fresh["release_sha256"]):
        raise ValueError("formal execution requires human review, adjudication and freeze")
    # Stage 1's execution_permitted=false is intentional. Stage 2 never trusts a
    # mutable enable flag: the independently reconstructed release is the gate.
    return fresh


def _tasks(plan: dict) -> list[str]:
    return [task for pack in plan["pack_ids"]
            for task in ([f"{pack}:extract"] +
                         [f"{qid}:{method}" for qid in plan["question_ids"]
                          if qid.startswith(f"{pack}-") for method in ("a", "b", "c")])]


@dataclass
class FormalCallRecorder:
    delegate: LLMClient
    path: Path
    calls: int = 0
    task_id: str | None = None
    pack_id: str | None = None
    method: str | None = None
    question_id: str | None = None

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        call_id = self.calls
        base = {"call_id": call_id, "task_id": self.task_id, "pack_id": self.pack_id,
                "method": self.method, "question_id": self.question_id,
                "stage": request.stage, "schema_name": request.schema_name,
                "request_sha256": _json_sha({"system_prompt": request.system_prompt,
                                              "payload": request.payload,
                                              "schema_name": request.schema_name})}
        _append_json(self.path, {"event": "begin", **base,
                                  "request": {"system_prompt": request.system_prompt,
                                              "payload": request.payload,
                                              "schema_name": request.schema_name}})
        started = time.perf_counter()
        try:
            response = self.delegate.complete_json(request)
        except Exception as exc:
            _append_json(self.path, {"event": "end", **base, "outcome": "error",
                                      "error_type": type(exc).__name__,
                                      "latency_ms": (time.perf_counter() - started) * 1000,
                                      "input_tokens": None, "output_tokens": None})
            raise
        _append_json(self.path, {"event": "end", **base, "outcome": "response",
                                  "response_model": response.model,
                                  "response_sha256": _json_sha(response.content),
                                  "response": response.content,
                                  "latency_ms": (time.perf_counter() - started) * 1000,
                                  "input_tokens": response.input_tokens,
                                  "output_tokens": response.output_tokens})
        return response


def _cost_plan(plan: dict):
    return plan_cost(
        max_requests=plan["max_api_requests"],
        max_input_tokens_per_request=plan["max_input_tokens_per_request"],
        max_output_tokens_per_request=plan["max_output_tokens_per_request"],
        max_cost_usd=plan["max_cost_usd"],
        input_usd_per_million=plan["input_usd_per_million"],
        output_usd_per_million=plan["output_usd_per_million"],
        price_source=plan["price_source"], price_date=plan["price_date"])


def _resume_state(run_dir: Path, plan: dict, expected_tasks: list[str], cost) -> tuple[list[str], int, int, int, Decimal]:
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("plan") != plan or manifest.get("task_ids") != expected_tasks
            or manifest.get("mode") not in {"INJECTED_OFFLINE", "LIVE"}):
        raise ValueError("resume manifest, configuration or task IDs differ")
    events = _read_jsonl(run_dir / "tasks.jsonl")
    completed: list[str] = []
    recorded_task_calls: dict[str, int] = {}
    active: str | None = None
    for event in events:
        task = event.get("task_id")
        if (event.get("event") == "begin" and active is None
                and len(completed) < len(expected_tasks)
                and task == expected_tasks[len(completed)]):
            active = task
        elif event.get("event") == "complete" and task == active:
            if type(event.get("requests")) is not int or event["requests"] < 0:
                raise ValueError("resume task request count is invalid")
            recorded_task_calls[task] = event["requests"]
            if task.endswith(":extract"):
                path = run_dir / "extractions" / f"{task.split(':')[0]}.json"
                if not path.is_file() or _sha(path.read_bytes()) != event.get("artifact_sha256"):
                    raise ValueError("resume extraction artifact hash mismatch")
            else:
                results = _read_jsonl(run_dir / "results.jsonl")
                row = next((item for item in results if item.get("task_id") == task), None)
                if row is None or _json_sha(row) != event.get("artifact_sha256"):
                    raise ValueError("resume answer row hash mismatch")
            completed.append(task)
            active = None
        else:
            raise ValueError("resume journal has failed, duplicated or out-of-order task")
    if active is not None:
        raise ValueError("resume has an in-flight or uncertain task; no automatic retry")
    results = _read_jsonl(run_dir / "results.jsonl")
    if [r.get("task_id") for r in results] != [t for t in completed if not t.endswith(":extract")]:
        raise ValueError("resume result rows differ from completed tasks")
    calls = _read_jsonl(run_dir / "calls.jsonl")
    if len(calls) % 2:
        raise ValueError("resume has an unmatched API request; no automatic retry")
    input_total = output_total = 0
    expense = Decimal(0)
    actual_task_calls = {task: 0 for task in completed}
    for index in range(0, len(calls), 2):
        begin, end = calls[index:index + 2]
        if (begin.get("event") != "begin" or end.get("event") != "end"
                or begin.get("call_id") != index // 2 + 1
                or end.get("call_id") != begin["call_id"]
                or end.get("task_id") != begin.get("task_id")
                or begin.get("task_id") not in completed
                or end.get("outcome") != "response"
                or end.get("response_model") != plan["model"]
                or _json_sha(begin.get("request")) != begin.get("request_sha256")):
            raise ValueError("resume call ledger contains uncertain or altered requests")
        inp, out = end.get("input_tokens"), end.get("output_tokens")
        if (type(inp) is not int or type(out) is not int or inp < 0 or out < 0
                or inp > cost.max_input_tokens_per_request
                or out > cost.max_output_tokens_per_request
                or _json_sha(end.get("response")) != end.get("response_sha256")):
            raise ValueError("resume call usage or response is invalid")
        input_total += inp
        output_total += out
        actual_task_calls[begin["task_id"]] += 1
        expense += (Decimal(inp) * cost.input_usd_per_million +
                    Decimal(out) * cost.output_usd_per_million) / Decimal(1_000_000)
    if actual_task_calls != recorded_task_calls:
        raise ValueError("resume task request counts differ from call ledger")
    if len(calls) // 2 > cost.max_requests or expense > cost.max_cost_usd:
        raise ValueError("resume ledger exceeds declared budget")
    return completed, len(calls) // 2, input_total, output_total, expense


def _write_summary(run_dir: Path, value: dict) -> None:
    temporary = run_dir / "summary.tmp"
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(run_dir / "summary.json")


def run_formal(plan_path: Path, inputs: FormalInputs, *, client: LLMClient,
               authorized: bool = False, resume: bool = False,
               max_tasks: int | None = None, mode: str = "INJECTED_OFFLINE") -> dict:
    """Run only after fresh preflight and explicit authorization.

    max_tasks is for bounded offline tests. A paused run may resume only at a
    completely journaled task boundary with known, bounded token usage.
    """
    if not authorized:
        raise ValueError("formal execution requires explicit authorization")
    if mode not in {"INJECTED_OFFLINE", "LIVE"}:
        raise ValueError("invalid formal run mode")
    if max_tasks is not None and (type(max_tasks) is not int or max_tasks < 1 or mode == "LIVE"):
        raise ValueError("max_tasks is available only for positive offline checks")
    plan = checked_plan(plan_path, inputs, resume=resume)
    if mode == "LIVE":
        _require_fresh_formal_price(plan)
    run_dir = Path(plan["planned_run_directory"])
    tasks = _tasks(plan)
    cost = _cost_plan(plan)
    if resume:
        completed, old_calls, old_in, old_out, old_cost = _resume_state(run_dir, plan, tasks, cost)
        manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        if manifest["mode"] != mode:
            raise ValueError("resume mode differs from original run")
    else:
        completed, old_calls, old_in, old_out, old_cost = [], 0, 0, 0, Decimal(0)
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "extractions").mkdir()
        _durable_json(run_dir / "run_manifest.json", {
            "schema_version": 1, "mode": mode, "plan": plan, "task_ids": tasks,
            "gold_used_by_model": False})
    recorder = FormalCallRecorder(client, run_dir / "calls.jsonl", calls=old_calls)
    guard = CostLimitedClient(recorder, cost, requests=old_calls,
                              input_tokens=old_in, output_tokens=old_out,
                              estimated_cost_usd=old_cost)
    proxy = _GuardProxy(guard)
    split = CandidateSplit.model_validate_json(inputs.split_path.read_text(encoding="utf-8"))
    all_records = load_csv(inputs.test_csv, preserve_explicit_ids=True)
    record_map = {record.record_id: record for record in all_records.records}
    questions = {q.question_id: q for q in (
        QuestionCandidate.model_validate(item) for item in
        json.loads(inputs.questions_path.read_text(encoding="utf-8")))
        if q.question_id in plan["question_ids"]}
    if len(questions) != 24:
        raise ValueError("formal runtime question ID mismatch")
    reason = None
    processed_now = 0
    try:
        for pack in plan["pack_ids"]:
            ids = split.packs[int(pack[1:]) - 1]
            records = RecordSet(records=[record_map[rid] for rid in ids])
            source_sha = dataset_fingerprint(records)
            extraction_task = f"{pack}:extract"
            if extraction_task in completed:
                extraction = ExtractionDataset.model_validate_json(
                    (run_dir / "extractions" / f"{pack}.json").read_text(encoding="utf-8"))
                if (extraction.fingerprint != source_sha or extraction.records != records.records
                        or extraction.provider_model != plan["model"]
                        or extraction.prompt_version != plan["prompt_versions"]["extraction"]
                        or extraction.coverage.failed_ids):
                    raise ValueError("resume extraction does not match its source")
            else:
                if max_tasks is not None and processed_now >= max_tasks:
                    break
                if guard.requests + 2 * 30 > cost.max_requests:
                    reason = "REQUEST_CEILING_REMAINING_TOO_SMALL"
                    break
                recorder.task_id, recorder.pack_id = extraction_task, pack
                recorder.method = "shared_extraction"
                recorder.question_id = None
                _append_json(run_dir / "tasks.jsonl", {"event": "begin", "task_id": extraction_task})
                outcome = ExtractionService(proxy, provider_model=plan["model"],
                                            prompt_version=plan["prompt_versions"]["extraction"]).extract(records)
                extraction = outcome.dataset
                path = run_dir / "extractions" / f"{pack}.json"
                _durable_json(path, extraction.model_dump(mode="json"))
                if guard.frozen or extraction.coverage.failed_ids:
                    reason = "EXTRACTION_COVERAGE_INCOMPLETE_OR_BUDGET_FROZEN"
                    _append_json(run_dir / "tasks.jsonl", {"event": "failed", "task_id": extraction_task,
                                                            "reason": reason,
                                                            "artifact_sha256": _sha(path.read_bytes())})
                    break
                _append_json(run_dir / "tasks.jsonl", {"event": "complete", "task_id": extraction_task,
                                                        "artifact_sha256": _sha(path.read_bytes()),
                                                        "source_sha256": source_sha,
                                                        "requests": outcome.requests})
                completed.append(extraction_task)
                processed_now += 1
            if reason:
                break
            extraction_hash = _sha((run_dir / "extractions" / f"{pack}.json").read_bytes())
            for qid in (q for q in plan["question_ids"] if q.startswith(f"{pack}-")):
                question = questions[qid]
                for method in ("a", "b", "c"):
                    task_id = f"{qid}:{method}"
                    if task_id in completed:
                        continue
                    if max_tasks is not None and processed_now >= max_tasks:
                        break
                    bound = conservative_request_bound(method, 30, prepared_extraction=True)
                    if guard.frozen or guard.requests + bound > cost.max_requests:
                        reason = "REQUEST_CEILING_REMAINING_TOO_SMALL_OR_BUDGET_FROZEN"
                        break
                    recorder.task_id, recorder.pack_id = task_id, pack
                    recorder.method, recorder.question_id = method, qid
                    before = guard.requests
                    _append_json(run_dir / "tasks.jsonl", {"event": "begin", "task_id": task_id})
                    try:
                        result = run_model_method(
                            records, method=method, question=question.wording,
                            question_id=qid, client=proxy, model_id=plan["model"],
                            max_api_requests=bound, max_records=30,
                            max_input_chars=plan["max_input_chars"],
                            extraction_dataset=None if method == "a" else extraction,
                            extraction_prompt_version=plan["prompt_versions"]["extraction"],
                            query_prompt_version=plan["prompt_versions"]["query"],
                            answer_prompt_version=plan["prompt_versions"]["answer"],
                            decision_prompt_version=plan["prompt_versions"]["decision"],
                            direct_prompt_version=plan["prompt_versions"]["direct"])
                        row = {"task_id": task_id, "pack_id": pack, "question_id": qid,
                               "method": method, "status": result.answer.status,
                               "answer": result.answer.model_dump(mode="json"),
                               "requests": guard.requests - before,
                               "source_sha256": source_sha,
                               "shared_extraction_sha256": extraction_hash if method != "a" else None}
                    except Exception as exc:
                        row = {"task_id": task_id, "pack_id": pack, "question_id": qid,
                               "method": method, "status": "execution_error",
                               "error_type": type(exc).__name__,
                               "requests": guard.requests - before,
                               "source_sha256": source_sha,
                               "shared_extraction_sha256": extraction_hash if method != "a" else None}
                        _append_json(run_dir / "results.jsonl", row)
                        reason = "METHOD_EXECUTION_ERROR"
                        _append_json(run_dir / "tasks.jsonl", {"event": "failed", "task_id": task_id,
                                                                "reason": reason,
                                                                "artifact_sha256": _json_sha(row)})
                        break
                    _append_json(run_dir / "results.jsonl", row)
                    _append_json(run_dir / "tasks.jsonl", {"event": "complete", "task_id": task_id,
                                                            "artifact_sha256": _json_sha(row),
                                                            "requests": guard.requests - before})
                    completed.append(task_id)
                    processed_now += 1
                if reason or (max_tasks is not None and processed_now >= max_tasks):
                    break
            if reason or (max_tasks is not None and processed_now >= max_tasks):
                break
    except BaseException:
        reason = reason or "UNEXPECTED_INTERRUPTION"
        raise
    finally:
        status = "COMPLETE" if len(completed) == len(tasks) and reason is None else (
            "PAUSED" if reason is None else "PARTIAL")
        answer_status_counts: dict[str, int] = {}
        for row in _read_jsonl(run_dir / "results.jsonl"):
            label = row.get("status", "unknown")
            answer_status_counts[label] = answer_status_counts.get(label, 0) + 1
        _write_summary(run_dir, {
            "status": status, "reason": reason, "plan_sha256": plan["plan_sha256"],
            "mode": mode, "planned_tasks": len(tasks), "completed_tasks": len(completed),
            "planned_method_answers": 72,
            "completed_method_answers": sum(not t.endswith(":extract") for t in completed),
            "recorded_answer_status_counts": answer_status_counts,
            "recorded_requests": guard.requests,
            "input_tokens": guard.input_tokens, "output_tokens": guard.output_tokens,
            "estimated_cost_usd": str(guard.estimated_cost_usd) if guard.estimated_cost_usd is not None else None,
            "budget_frozen": guard.frozen,
            "formal_score_computed": False,
        })
    return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))


def _require_fresh_formal_price(plan: dict) -> None:
    source = plan["price_source"].lower()
    if "assumption" in source or "historical" in source:
        raise ValueError("formal live pricing must be independently refreshed from an official source")
    if (date.today() - date.fromisoformat(plan["price_date"])).days not in range(0, 8):
        raise ValueError("formal price assumptions must be refreshed within seven days")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Formal A/B/C runner; dry precheck by default")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--lock", default="configs/formal_24_candidate.lock.json")
    parser.add_argument("--split", default="data/processed/candidate_split.json")
    parser.add_argument("--test-csv", default="data/processed/test.csv")
    parser.add_argument("--dev-csv", default="data/processed/dev.csv")
    parser.add_argument("--questions", default="data/processed/candidate_questions.json")
    parser.add_argument("--references", default="data/gold/candidate_references.json")
    parser.add_argument("--test-gold", default="data/gold/test.json")
    parser.add_argument("--metrics-code", default="eval/metrics.py")
    parser.add_argument("--reviewer-1", required=True)
    parser.add_argument("--reviewer-2", required=True)
    parser.add_argument("--adjudication")
    parser.add_argument("--release")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorize-formal-live", action="store_true")
    parser.add_argument("--plan-sha256")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    inputs = FormalInputs(
        lock_path=Path(args.lock), split_path=Path(args.split),
        test_csv=Path(args.test_csv), dev_csv=Path(args.dev_csv),
        questions_path=Path(args.questions), references_path=Path(args.references),
        test_gold_path=Path(args.test_gold), metrics_path=Path(args.metrics_code),
        reviewer_1_path=Path(args.reviewer_1), reviewer_2_path=Path(args.reviewer_2),
        adjudication_path=Path(args.adjudication) if args.adjudication else None,
        release_path=Path(args.release) if args.release else None)
    try:
        plan = checked_plan(Path(args.plan), inputs, resume=args.resume)
        if not args.execute:
            print(json.dumps({"mode": "PREFLIGHT_ONLY", "network_calls_made": 0,
                              "plan_sha256": plan["plan_sha256"],
                              "material_state": plan["material_state"]}))
            return 0
        if not args.authorize_formal_live or args.plan_sha256 != plan["plan_sha256"]:
            raise ValueError("live formal run requires explicit authorization and exact plan hash")
        _require_fresh_formal_price(plan)
        if not os.environ.get("DEEPSEEK_API_KEY"):
            raise ValueError("DEEPSEEK_API_KEY is unavailable")
        require_dev_run_balance(plan["max_cost_usd"])
        client = ResponsesClient("deepseek", plan["model"],
                                 max_output_tokens=plan["max_output_tokens_per_request"],
                                 timeout_seconds=plan["timeout_seconds"], allow_network=True)
        summary = run_formal(Path(args.plan), inputs, client=client,
                             authorized=True, resume=args.resume, mode="LIVE")
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary["status"] == "COMPLETE" else 3
    except (OSError, ValueError, KeyError, TypeError, BudgetError, BalanceError) as exc:
        print(f"formal preflight/run refused: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
