"""Frozen 40-pair Challenge extraction; dry preflight unless explicitly executed.

The human references are validated in preflight only. The model loop receives
finalized sentence text and IDs, never Gold labels or adjudication notes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from eval.challenge_metrics import ChallengeReference
from scripts.run_dev_pilot import _GuardProxy, _append_json, _durable_json
from scripts.run_formal_experiment import FormalCallRecorder, _read_jsonl, _write_summary
from src.absa_service import ExtractionService
from src.deepseek_balance import BalanceError, require_formal_run_balance
from src.live_cost import BudgetError, CostLimitedClient, plan_cost
from src.llm_client import LLMClient
from src.responses_client import ResponsesClient
from src.schemas import Record, RecordSet


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()


def _material(pairs_path: Path, references_path: Path, release_path: Path) -> list[dict]:
    release = json.loads(release_path.read_text(encoding="utf-8"))
    if (release.get("status") != "HUMAN_ADJUDICATED_GOLD_FROZEN"
            or release.get("pair_count") != 40 or release.get("source_record_count") != 80
            or release.get("model_run_status") != "NOT_RUN"):
        raise ValueError("Challenge human Gold release is not the frozen 40-pair version")
    owner_path = references_path.parent / "owner_adjudication.json"
    if (_sha(pairs_path) != release.get("source_sha256", {}).get("final_candidate_pairs")
            or _sha(references_path) != release.get("references_sha256")
            or _sha(owner_path) != release.get("owner_adjudication_sha256")):
        raise ValueError("Challenge text, references or owner adjudication hash mismatch")
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    if (owner.get("status") != "OWNER_ADJUDICATED"
            or owner.get("unresolved_owner_decisions") not in (None, [])
            or release.get("reviewer_ids") != ["R1", "R2"]
            or not release.get("adjudicator_id")):
        raise ValueError("Challenge owner adjudication or reviewer provenance is incomplete")
    if _sha(Path("eval/challenge_metrics.py")) != release.get("scorer_source_sha256"):
        raise ValueError("Challenge scorer differs from frozen release")
    source_files = {
        "R1_original_paste": "R1_original_paste.txt",
        "R2_original_paste": "R2_original_paste.txt",
        "R1_parsed": "R1_parsed.json",
        "R2_parsed": "R2_parsed.json",
        "comparison_40": "comparison_40.json",
    }
    review_dir = Path("outputs/challenge_label_review_2026-11-27")
    for key, name in source_files.items():
        if _sha(review_dir / name) != release["source_sha256"][key]:
            raise ValueError(f"Challenge reviewer source hash mismatch: {key}")
    reviewer_labels = [json.loads((review_dir / f"R{number}_parsed.json").read_text(encoding="utf-8"))
                       for number in (1, 2)]
    pairs_doc = json.loads(pairs_path.read_text(encoding="utf-8"))
    pairs = pairs_doc.get("pairs")
    raw_refs = json.loads(references_path.read_text(encoding="utf-8"))
    if not isinstance(pairs, list) or not isinstance(raw_refs, list) or len(pairs) != len(raw_refs) or len(pairs) != 40:
        raise ValueError("Challenge pair or Gold count mismatch")
    refs = [ChallengeReference.model_validate(item) for item in raw_refs]
    if (len({ref.pair_id for ref in refs}) != 40
            or sum(len(ref.intended_change_categories) for ref in refs) != release.get("changed_category_units")
            or sum(len(ref.stable_categories) for ref in refs) != release.get("stable_category_units")):
        raise ValueError("Challenge Gold pair IDs or units mismatch")
    seen: set[str] = set()
    for number, (pair, ref) in enumerate(zip(pairs, refs), 1):
        pid = f"CH{number:03d}"
        if pair.get("pair_id") != ref.pair_id or ref.pair_id != pid:
            raise ValueError("Challenge pair ordering or ID mismatch")
        if pair.get("text_origin") != "CODEX_DRAFT_HUMAN_REVIEWED":
            raise ValueError("Challenge text origin mismatch")
        if ref.annotation_record_sha256 != release["owner_adjudication_sha256"]:
            raise ValueError("Challenge Gold annotation provenance mismatch")
        before = {aspect.category.value: aspect.sentiment.value for aspect in ref.source_gold.aspects}
        after = {aspect.category.value: aspect.sentiment.value for aspect in ref.edited_gold.aspects}
        for reviewer in reviewer_labels:
            if (reviewer[pid]["source_labels"] != before or reviewer[pid]["edited_labels"] != after
                    or sorted(reviewer[pid]["computed_changed_categories"]) != sorted(c.value for c in ref.intended_change_categories)
                    or sorted(reviewer[pid]["computed_stable_categories"]) != sorted(c.value for c in ref.stable_categories)):
                raise ValueError("Challenge frozen Gold differs from independent reviewer labels")
        for side, gold in (("source", ref.source_gold), ("edited", ref.edited_gold)):
            record = Record.model_validate(pair[side])
            if record.record_id != gold.record_id or record.record_id in seen:
                raise ValueError("Challenge record ID or Gold alignment mismatch")
            seen.add(record.record_id)
    if len(seen) != 80:
        raise ValueError("Challenge must have 80 distinct record IDs")
    if (next(ref for ref in refs if ref.pair_id == "CH018").stable_categories
            or "CH023" not in release.get("ambiguity_retained_pair_ids", [])):
        raise ValueError("Challenge CH018/CH023 owner decisions are missing")
    return pairs


def build_plan(*, pairs_path: Path, references_path: Path, release_path: Path,
               run_dir: Path, model: str, max_requests: int,
               max_input_tokens: int, max_output_tokens: int, max_cost_usd: str,
               input_usd_per_million: str, output_usd_per_million: str,
               price_source: str, price_date: str, timeout_seconds: float) -> dict:
    pairs = _material(pairs_path, references_path, release_path)
    if model != "deepseek-flash" or max_requests != 160 or timeout_seconds <= 0:
        raise ValueError("Challenge model, 160-request ceiling or timeout mismatch")
    if not str(run_dir).startswith("outputs") or run_dir.exists():
        raise ValueError("Challenge run directory must be a new local outputs path")
    cost = plan_cost(max_requests=max_requests, max_input_tokens_per_request=max_input_tokens,
                     max_output_tokens_per_request=max_output_tokens,
                     max_cost_usd=max_cost_usd, input_usd_per_million=input_usd_per_million,
                     output_usd_per_million=output_usd_per_million,
                     price_source=price_source, price_date=price_date)
    plan = {
        "status": "FROZEN_PREFLIGHT_READY", "provider": "deepseek", "model": model,
        "prompt_version": "extract-v2", "reasoning_effort": "none",
        "pair_count": len(pairs), "record_count": 80,
        "pairs_path": str(pairs_path), "references_path": str(references_path),
        "release_path": str(release_path), "run_dir": str(run_dir),
        "pairs_sha256": _sha(pairs_path), "references_sha256": _sha(references_path),
        "release_sha256": _sha(release_path),
        "extraction_prompt_source_sha256": _sha(Path("src/absa_service/extractor.py")),
        "runner_source_sha256": _sha(Path(__file__)),
        "max_requests": cost.max_requests,
        "max_input_tokens_per_request": cost.max_input_tokens_per_request,
        "max_output_tokens_per_request": cost.max_output_tokens_per_request,
        "max_cost_usd": str(cost.max_cost_usd),
        "worst_case_usd": str(cost.worst_case_usd),
        "input_usd_per_million": str(cost.input_usd_per_million),
        "output_usd_per_million": str(cost.output_usd_per_million),
        "price_source": cost.price_source, "price_date": cost.price_date,
        "timeout_seconds": timeout_seconds,
        "gold_used_by_model": False,
    }
    plan["plan_sha256"] = _json_sha(plan)
    return plan


def checked_plan(plan_path: Path, *, resume: bool = False) -> tuple[dict, list[dict]]:
    saved = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(saved, dict):
        raise ValueError("Challenge plan must be an object")
    try:
        run_dir = Path(saved["run_dir"])
        if resume and not run_dir.is_dir():
            raise ValueError("Challenge resume directory is missing")
        if resume:
            # The builder demands a fresh path; temporarily inspect the path
            # separately, then rebuild against a sibling that cannot exist.
            fresh_path = run_dir.with_name(run_dir.name + ".preflight-nonexistent")
            if fresh_path.exists():
                raise ValueError("Challenge preflight sentinel path exists")
        else:
            fresh_path = run_dir
        fresh = build_plan(
            pairs_path=Path(saved["pairs_path"]), references_path=Path(saved["references_path"]),
            release_path=Path(saved["release_path"]), run_dir=fresh_path,
            model=saved["model"], max_requests=saved["max_requests"],
            max_input_tokens=saved["max_input_tokens_per_request"],
            max_output_tokens=saved["max_output_tokens_per_request"],
            max_cost_usd=saved["max_cost_usd"], input_usd_per_million=saved["input_usd_per_million"],
            output_usd_per_million=saved["output_usd_per_million"],
            price_source=saved["price_source"], price_date=saved["price_date"],
            timeout_seconds=saved["timeout_seconds"])
    except (KeyError, TypeError) as exc:
        raise ValueError("Challenge plan is missing required configuration") from exc
    if resume:
        fresh["run_dir"] = saved["run_dir"]
        fresh["plan_sha256"] = _json_sha({k: v for k, v in fresh.items() if k != "plan_sha256"})
    if saved != fresh:
        raise ValueError("Challenge plan differs from frozen inputs or configuration")
    return fresh, _material(Path(saved["pairs_path"]), Path(saved["references_path"]),
                            Path(saved["release_path"]))


def _resume(run_dir: Path, plan: dict, task_ids: list[str], cost) -> tuple[list[str], int, int, int, Decimal]:
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("plan") != plan or manifest.get("task_ids") != task_ids:
        raise ValueError("Challenge resume manifest or tasks mismatch")
    events = _read_jsonl(run_dir / "tasks.jsonl")
    completed: list[str] = []
    active = None
    task_calls: dict[str, int] = {}
    for event in events:
        tid = event.get("task_id")
        if event.get("event") == "begin" and active is None and len(completed) < 80 and tid == task_ids[len(completed)]:
            active = tid
        elif event.get("event") == "complete" and tid == active:
            path = run_dir / "records" / f"{tid}.json"
            if _sha(path) != event.get("artifact_sha256") or type(event.get("requests")) is not int:
                raise ValueError("Challenge completed record hash or request count mismatch")
            task_calls[tid] = event["requests"]
            completed.append(tid)
            active = None
        else:
            raise ValueError("Challenge resume task journal is inconsistent")
    if active is not None:
        raise ValueError("Challenge has an in-flight or unknown task; no automatic replay")
    calls = _read_jsonl(run_dir / "calls.jsonl")
    if len(calls) % 2:
        raise ValueError("Challenge has an unmatched request; no automatic replay")
    input_total = output_total = 0
    expense = Decimal(0)
    seen_calls = {task: 0 for task in completed}
    for index in range(0, len(calls), 2):
        begin, end = calls[index:index+2]
        tid = begin.get("task_id")
        if (begin.get("event") != "begin" or end.get("event") != "end"
                or begin.get("call_id") != index // 2 + 1 or end.get("call_id") != begin["call_id"]
                or tid not in seen_calls or end.get("task_id") != tid
                or end.get("outcome") != "response" or end.get("response_model") != plan["model"]
                or _json_sha(begin.get("request")) != begin.get("request_sha256")
                or _json_sha(end.get("response")) != end.get("response_sha256")):
            raise ValueError("Challenge call ledger has unknown or changed requests")
        inp, out = end.get("input_tokens"), end.get("output_tokens")
        if (type(inp) is not int or type(out) is not int or inp < 0 or out < 0
                or inp > cost.max_input_tokens_per_request or out > cost.max_output_tokens_per_request):
            raise ValueError("Challenge call usage is missing or out of bounds")
        input_total += inp
        output_total += out
        expense += (Decimal(inp) * cost.input_usd_per_million +
                    Decimal(out) * cost.output_usd_per_million) / Decimal(1_000_000)
        seen_calls[tid] += 1
    if seen_calls != task_calls or len(calls) // 2 > cost.max_requests or expense > cost.max_cost_usd:
        raise ValueError("Challenge resume ledger differs from completed tasks or budget")
    return completed, len(calls) // 2, input_total, output_total, expense


def run_challenge(plan_path: Path, *, client: LLMClient, authorized: bool = False,
                  mode: str = "INJECTED_OFFLINE", resume: bool = False,
                  max_records: int | None = None) -> dict:
    if not authorized or mode not in {"INJECTED_OFFLINE", "LIVE"}:
        raise ValueError("Challenge execution requires explicit authorization and valid mode")
    if max_records is not None and (mode == "LIVE" or type(max_records) is not int or max_records < 1):
        raise ValueError("max_records is only for positive offline tests")
    plan, pairs = checked_plan(plan_path, resume=resume)
    if mode == "LIVE":
        _fresh_price(plan)
    cost = plan_cost(max_requests=plan["max_requests"],
                     max_input_tokens_per_request=plan["max_input_tokens_per_request"],
                     max_output_tokens_per_request=plan["max_output_tokens_per_request"],
                     max_cost_usd=plan["max_cost_usd"],
                     input_usd_per_million=plan["input_usd_per_million"],
                     output_usd_per_million=plan["output_usd_per_million"],
                     price_source=plan["price_source"], price_date=plan["price_date"])
    run_dir = Path(plan["run_dir"])
    records = [Record.model_validate(pair[side]) for pair in pairs for side in ("source", "edited")]
    task_ids = [record.record_id for record in records]
    if resume:
        completed, old_calls, old_in, old_out, old_cost = _resume(run_dir, plan, task_ids, cost)
        if json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))["mode"] != mode:
            raise ValueError("Challenge resume mode mismatch")
    else:
        completed, old_calls, old_in, old_out, old_cost = [], 0, 0, 0, Decimal(0)
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "records").mkdir()
        (run_dir / "predictions").mkdir()
        _durable_json(run_dir / "run_manifest.json", {"mode": mode, "plan": plan,
                      "task_ids": task_ids, "gold_used_by_model": False})
    recorder = FormalCallRecorder(client, run_dir / "calls.jsonl", calls=old_calls)
    guard = CostLimitedClient(recorder, cost, requests=old_calls, input_tokens=old_in,
                              output_tokens=old_out, estimated_cost_usd=old_cost)
    reason = None
    processed_now = 0
    try:
        for record in records[len(completed):]:
            if max_records is not None and processed_now >= max_records:
                break
            if guard.frozen or guard.requests + 2 > cost.max_requests:
                reason = "BUDGET_GATE_CLOSED"
                break
            tid = record.record_id
            recorder.task_id = tid
            recorder.method = "challenge_extraction"
            _append_json(run_dir / "tasks.jsonl", {"event": "begin", "task_id": tid})
            before = guard.requests
            extraction = ExtractionService(_GuardProxy(guard), provider_model=plan["model"],
                                           prompt_version=plan["prompt_version"]).extract(RecordSet(records=[record]))
            result = extraction.dataset.extractions[0]
            row = {"task_id": tid, "status": result.status,
                   "extraction": result.model_dump(mode="json"),
                   "requests": guard.requests - before,
                   "attempt_diagnostics": extraction.attempt_diagnostics}
            path = run_dir / "records" / f"{tid}.json"
            _durable_json(path, row)
            _append_json(run_dir / "tasks.jsonl", {"event": "complete", "task_id": tid,
                         "requests": row["requests"], "artifact_sha256": _sha(path)})
            completed.append(tid)
            processed_now += 1
            if guard.frozen:
                reason = "UNKNOWN_COST_OR_TRANSPORT"
                break
        if len(completed) == 80 and reason is None:
            for pair in pairs:
                pid = pair["pair_id"]
                results = [json.loads((run_dir / "records" / f"{pair[side]['record_id']}.json").read_text(encoding="utf-8"))["extraction"]
                           for side in ("source", "edited")]
                payload = {"mode": "LIVE" if mode == "LIVE" else "MOCK",
                           "condition": "challenge", "pair_id": pid,
                           "predictions": results, "scores": None, "human_labels": None,
                           "plan_sha256": plan["plan_sha256"]}
                path = run_dir / "predictions" / f"{pid}.json"
                if path.exists():
                    if json.loads(path.read_text(encoding="utf-8")) != payload:
                        raise ValueError("Challenge prediction artifact mismatch")
                else:
                    _durable_json(path, payload)
    except BaseException:
        reason = reason or "UNEXPECTED_INTERRUPTION"
        raise
    finally:
        status = "COMPLETE" if len(completed) == 80 and reason is None else (
            "PAUSED" if reason is None else "PARTIAL")
        failed = sum(json.loads((run_dir / "records" / f"{tid}.json").read_text(encoding="utf-8"))["status"] == "failed"
                     for tid in completed)
        _write_summary(run_dir, {"status": status, "reason": reason, "mode": mode,
            "plan_sha256": plan["plan_sha256"], "planned_records": 80,
            "completed_records": len(completed), "failed_extractions": failed,
            "recorded_requests": guard.requests, "input_tokens": guard.input_tokens,
            "output_tokens": guard.output_tokens,
            "estimated_cost_usd": str(guard.estimated_cost_usd) if guard.estimated_cost_usd is not None else None,
            "budget_frozen": guard.frozen, "challenge_score_computed": False})
    return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))


def _fresh_price(plan: dict) -> None:
    if ("assumption" in plan["price_source"].lower()
            or "historical" in plan["price_source"].lower()
            or (date.today() - date.fromisoformat(plan["price_date"])).days not in range(0, 8)):
        raise ValueError("Challenge live pricing requires recent official verification")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen Challenge runner; dry preflight by default")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorize-challenge-live", action="store_true")
    parser.add_argument("--plan-sha256")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan, _ = checked_plan(Path(args.plan), resume=args.resume)
        if not args.execute:
            print(json.dumps({"mode": "PREFLIGHT_ONLY", "network_calls_made": 0,
                              "plan_sha256": plan["plan_sha256"], "record_count": 80}))
            return 0
        if not args.authorize_challenge_live or args.plan_sha256 != plan["plan_sha256"]:
            raise ValueError("Challenge live execution needs explicit authorization and exact plan hash")
        _fresh_price(plan)
        if not os.environ.get("DEEPSEEK_API_KEY"):
            raise ValueError("DEEPSEEK_API_KEY is unavailable")
        require_formal_run_balance(plan["worst_case_usd"])
        client = ResponsesClient("deepseek", plan["model"],
                                 max_output_tokens=plan["max_output_tokens_per_request"],
                                 timeout_seconds=plan["timeout_seconds"], allow_network=True)
        summary = run_challenge(Path(args.plan), client=client, authorized=True,
                                mode="LIVE", resume=args.resume)
        print(json.dumps(summary))
        return 0 if summary["status"] == "COMPLETE" else 2
    except (ValueError, OSError, KeyError, BudgetError, BalanceError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": type(exc).__name__,
                          "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
