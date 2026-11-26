"""Offline, hash-bound preflight for the fixed four-Pack formal candidate set.

This module has no provider client and cannot execute a formal experiment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

from eval.question_audit import TASK_TYPES, audit_candidate_questions
from eval.questions import GoldReference, QuestionCandidate
from scripts.audit_question_review import _JUDGMENTS, _read_sheet
from src.data_loader import load_csv
from src.live_cost import BudgetError, plan_cost
from src.live_runtime import conservative_request_bound
from src.semeval import CandidateSplit


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _review_csv(path: Path, slot: int, packs: list[str]) -> bytes:
    if path.suffix.lower() != ".zip":
        return path.read_bytes()
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("review packet ZIP is corrupt")
        manifest = json.loads(archive.read("MANIFEST.json"))
        if (manifest.get("reviewer_slot") != slot or manifest.get("question_rows") != 24
                or manifest.get("selected_pack_ids") != packs):
            raise ValueError("review packet identity or selected Packs differ")
        for name, digest in manifest["files_sha256"].items():
            if _sha(archive.read(name)) != digest:
                raise ValueError("review packet file hash mismatch")
        return archive.read(f"02_questions/reviewer_{slot}.csv")


def _review_state(rows_1: list[dict[str, str]], rows_2: list[dict[str, str]],
                  reviewer_1: str | None, reviewer_2: str | None) -> tuple[str, list[str]]:
    if (reviewer_1 is not None and reviewer_1 != "R1"
            or reviewer_2 is not None and reviewer_2 != "R2"):
        raise ValueError("reviewer IDs must match the independent R1/R2 sheets")
    if reviewer_1 and reviewer_2 and reviewer_1 == reviewer_2:
        raise ValueError("independent review sheets have the same reviewer ID")
    if (not reviewer_1 or not reviewer_2
            or any(not row["reviewer_id"].strip() or any(not row[k].strip() for k in _JUDGMENTS)
                   for rows in (rows_1, rows_2) for row in rows)):
        return "PENDING_HUMAN_REVIEW", []
    flagged = [left["question_id"] for left, right in zip(rows_1, rows_2, strict=True)
               if any(left[k].lower() == "no" or right[k].lower() == "no"
                      or left[k].lower() != right[k].lower() for k in _JUDGMENTS)
               or left["proposed_edit"].strip() or right["proposed_edit"].strip()]
    return "REVIEWED_AWAITING_ADJUDICATION_AND_FREEZE", flagged


def _release_state(*, release_path: Path | None, adjudication_path: Path | None,
                   review_state: str, flagged: list[str], qids: list[str], packs: list[str],
                   source_hashes: dict[str, str], sheet_hashes: dict[str, str],
                   rubric: str, reviewer_ids: tuple[str | None, str | None]) -> tuple[str, str | None]:
    if release_path is None and adjudication_path is None:
        return "CANDIDATE_UNFROZEN", None
    if release_path is None or adjudication_path is None:
        raise ValueError("release and adjudication records must be supplied together")
    if review_state == "PENDING_HUMAN_REVIEW":
        raise ValueError("human review is incomplete; release is prohibited")
    adjudication = json.loads(adjudication_path.read_text(encoding="utf-8"))
    release = json.loads(release_path.read_text(encoding="utf-8"))
    adjudicator = adjudication.get("adjudicator_id")
    resolved = adjudication.get("resolved_question_ids")
    if (adjudication.get("status") != "HUMAN_ADJUDICATED"
            or not isinstance(adjudicator, str) or not adjudicator.strip()
            or adjudicator in reviewer_ids
            or not isinstance(resolved, list) or len(resolved) != len(set(resolved))
            or not set(flagged).issubset(set(resolved))
            or not set(resolved).issubset(set(qids))):
        raise ValueError("adjudication record is incomplete or inconsistent")
    signer = release.get("signed_off_by")
    if (release.get("status") != "FROZEN"
            or not isinstance(signer, str) or not signer.strip()
            or release.get("pack_ids") != packs or release.get("question_ids") != qids
            or release.get("source_sha256") != source_hashes
            or release.get("review_sheet_sha256") != sheet_hashes
            or release.get("adjudication_sha256") != _file_sha(adjudication_path)
            or release.get("scoring_rule_version") != rubric):
        raise ValueError("freeze record does not bind the reviewed sources and scoring rule")
    return "FROZEN", _file_sha(release_path)


def build_plan(*, lock_path: Path, split_path: Path, test_csv: Path, dev_csv: Path,
               questions_path: Path, references_path: Path, test_gold_path: Path,
               metrics_path: Path, reviewer_1_path: Path, reviewer_2_path: Path,
               run_dir: Path, provider: str, model: str, max_input_chars: int,
               max_input_tokens: int, max_output_tokens: int, max_api_requests: int,
               max_cost_usd: str, input_usd_per_million: str,
               output_usd_per_million: str, price_source: str, price_date: str,
               timeout_seconds: float, release_path: Path | None = None,
               adjudication_path: Path | None = None,
               allow_existing_run_dir: bool = False) -> dict:
    if run_dir.exists() and not allow_existing_run_dir:
        raise ValueError("run directory already exists")
    if provider != "deepseek" or model != "deepseek-flash":
        raise ValueError("formal model must match the declared DeepSeek configuration")
    if not 0 < timeout_seconds <= 120:
        raise ValueError("timeout must be positive and at most 120 seconds")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    packs = lock.get("pack_ids")
    if (lock.get("status") != "CANDIDATE_UNREVIEWED"
            or packs != ["P01", "P06", "P11", "P16"]
            or len(lock.get("question_ids", [])) != 24
            or len(set(lock["question_ids"])) != 24
            or lock.get("scoring_rule_version") not in {"strict", "bounded_aliases_v1"}
            or set(lock.get("prompt_versions", {})) !=
            {"extraction", "query", "answer", "decision", "direct"}):
        raise ValueError("formal candidate lock is invalid")
    paths = {"split": split_path, "test_csv": test_csv, "dev_csv": dev_csv,
             "questions": questions_path, "references": references_path,
             "test_gold": test_gold_path, "metrics_code": metrics_path}
    actual_hashes = {name: _file_sha(path) for name, path in paths.items()}
    if actual_hashes != lock.get("source_sha256"):
        raise ValueError("formal input file hash mismatch")
    split = CandidateSplit.model_validate_json(split_path.read_text(encoding="utf-8"))
    test = load_csv(test_csv, preserve_explicit_ids=True)
    dev = load_csv(dev_csv, preserve_explicit_ids=True)
    test_ids = [r.record_id for r in test.records]
    dev_ids = [r.record_id for r in dev.records]
    if (len(split.packs) != 20 or len(test_ids) != 600 or len(dev_ids) != 150
            or test_ids != split.test_ids or dev_ids != split.dev_ids
            or set(test_ids) & set(dev_ids)):
        raise ValueError("formal and development CSVs do not match isolated split IDs")
    all_q = [QuestionCandidate.model_validate(x) for x in
             json.loads(questions_path.read_text(encoding="utf-8"))]
    all_r = [GoldReference.model_validate(x) for x in
             json.loads(references_path.read_text(encoding="utf-8"))]
    if len(all_q) != 120 or len({q.question_id for q in all_q}) != 120:
        raise ValueError("source question IDs are missing or repeated")
    selected_q = [q for q in all_q if q.pack_id in packs]
    selected_ids = {q.question_id for q in selected_q}
    selected_r = [r for r in all_r if r.question_id in selected_ids]
    subset_audit = audit_candidate_questions(selected_q, selected_r, expected_packs=4)
    if (len(selected_q) != 24 or [q.question_id for q in selected_q] != lock["question_ids"]
            or subset_audit["questions_sha256"] != lock.get("selected_questions_sha256")
            or subset_audit["references_sha256"] != lock.get("selected_references_sha256")
            or subset_audit["pack_issues"] or subset_audit["pack_scope_issues"]
            or subset_audit["cross_pack_overlap"]):
        raise ValueError("fixed 24 question IDs, references or Pack structure differ")
    selected_records = []
    for position, pack_id in enumerate(packs):
        ids = split.packs[int(pack_id[1:]) - 1]
        per_pack = [q for q in selected_q if q.pack_id == pack_id]
        if (len(ids) != 30 or len(per_pack) != 6
                or {q.task_type for q in per_pack} != TASK_TYPES
                or any(q.record_ids != ids or q.status != "CANDIDATE_UNREVIEWED"
                       for q in per_pack)):
            raise ValueError(f"Pack {pack_id} does not match the split and six task types")
        selected_records.extend(ids)
    if len(selected_records) != 120 or len(set(selected_records)) != 120:
        raise ValueError("selected Pack records repeat or are missing")
    references_by_id = {r.question_id: r for r in selected_r}
    if any(references_by_id[q.question_id].status != "CANDIDATE_UNREVIEWED" for q in selected_q):
        raise ValueError("candidate references have unexpected status")
    # _read_sheet validates immutable question fields, reference JSON and subset hashes.
    sheet_bytes = {"R1": _review_csv(reviewer_1_path, 1, packs),
                   "R2": _review_csv(reviewer_2_path, 2, packs)}
    with tempfile.TemporaryDirectory() as temporary:
        paths_by_slot = {}
        for slot, content in sheet_bytes.items():
            path = Path(temporary) / f"{slot}.csv"
            path.write_bytes(content)
            paths_by_slot[slot] = path
        rows_1, reviewer_1 = _read_sheet(paths_by_slot["R1"], selected_q,
                                         references_by_id, subset_audit)
        rows_2, reviewer_2 = _read_sheet(paths_by_slot["R2"], selected_q,
                                         references_by_id, subset_audit)
    review_state, flagged = _review_state(rows_1, rows_2, reviewer_1, reviewer_2)
    sheet_hashes = {slot: _sha(content) for slot, content in sheet_bytes.items()}
    state, release_sha = _release_state(
        release_path=release_path, adjudication_path=adjudication_path,
        review_state=review_state, flagged=flagged, qids=lock["question_ids"],
        packs=packs, source_hashes=actual_hashes, sheet_hashes=sheet_hashes,
        rubric=lock["scoring_rule_version"], reviewer_ids=(reviewer_1, reviewer_2))
    record_by_id = {record.record_id: record for record in test.records}
    source_chars = max(sum(len(record_by_id[rid].text) for rid in split.packs[int(p[1:]) - 1])
                       for p in packs)
    max_question_chars = max(len(q.wording) for q in selected_q)
    if (type(max_input_chars) is not int or max_input_chars < source_chars + max_question_chars):
        raise ValueError("input character cap is too small for a selected Pack and question")
    extraction_bound = 2 * len(selected_records)
    method_bounds = {method: conservative_request_bound(method, 30, prepared_extraction=True) * len(selected_q)
                     for method in ("a", "b", "c")}
    request_ceiling = extraction_bound + sum(method_bounds.values())
    if type(max_api_requests) is not int or max_api_requests != request_ceiling:
        raise ValueError("request cap must equal the conservative full A/B/C bound")
    cost = plan_cost(max_requests=max_api_requests,
                     max_input_tokens_per_request=max_input_tokens,
                     max_output_tokens_per_request=max_output_tokens,
                     max_cost_usd=max_cost_usd,
                     input_usd_per_million=input_usd_per_million,
                     output_usd_per_million=output_usd_per_million,
                     price_source=price_source, price_date=price_date)
    plan = {
        "status": "FROZEN_PREFLIGHT_READY" if state == "FROZEN" else "CANDIDATE_PREFLIGHT_ONLY",
        "execution_permitted": False, "material_gate_passed": state == "FROZEN",
        "network_calls_made": 0,
        "material_state": state, "question_review_state": review_state,
        "provider": provider, "model": model, "reasoning_effort": "none",
        "prompt_versions": lock["prompt_versions"],
        "scoring_rule_version": lock["scoring_rule_version"],
        "methods": ["a", "b", "c"], "pack_ids": packs,
        "question_ids": lock["question_ids"], "record_count": 120, "question_count": 24,
        "lock_sha256": _file_sha(lock_path), "source_sha256": actual_hashes,
        "review_sheet_sha256": sheet_hashes,
        "selected_questions_sha256": subset_audit["questions_sha256"],
        "selected_references_sha256": subset_audit["references_sha256"],
        "release_sha256": release_sha,
        "source_review_chars_max_pack": source_chars,
        "max_question_chars": max_question_chars,
        "max_input_chars": max_input_chars,
        "shared_extraction_request_bound": extraction_bound,
        "method_request_bounds": method_bounds,
        "max_api_requests": max_api_requests,
        "max_input_tokens_per_request": max_input_tokens,
        "max_output_tokens_per_request": max_output_tokens,
        "max_cost_usd": str(cost.max_cost_usd),
        "declared_worst_case_usd": str(cost.worst_case_usd),
        "input_usd_per_million": str(cost.input_usd_per_million),
        "output_usd_per_million": str(cost.output_usd_per_million),
        "price_source": cost.price_source, "price_date": cost.price_date,
        "timeout_seconds": timeout_seconds,
        "planned_run_directory": str(run_dir),
        "formal_runner_implemented": False,
    }
    plan["plan_sha256"] = _sha(json.dumps(plan, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8"))
    return plan


def require_formal_execution_ready(plan: dict) -> None:
    """Fail closed until both a frozen plan and a separate runner exist."""
    if (plan.get("status") != "FROZEN_PREFLIGHT_READY"
            or plan.get("material_state") != "FROZEN"
            or plan.get("material_gate_passed") is not True
            or not plan.get("release_sha256")):
        raise ValueError("formal execution requires completed review, adjudication and freeze")
    if plan.get("formal_runner_implemented") is not True:
        raise ValueError("formal execution runner has not been implemented")
    if plan.get("execution_permitted") is not True:
        raise ValueError("formal execution is disabled")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline formal 13+24 candidate Plan/Preflight; no API calls")
    parser.add_argument("--lock", default="configs/formal_24_candidate.lock.json")
    parser.add_argument("--split", default="data/processed/candidate_split.json")
    parser.add_argument("--test-csv", default="data/processed/test.csv")
    parser.add_argument("--dev-csv", default="data/processed/dev.csv")
    parser.add_argument("--questions", default="data/processed/candidate_questions.json")
    parser.add_argument("--references", default="data/gold/candidate_references.json")
    parser.add_argument("--test-gold", default="data/gold/test.json")
    parser.add_argument("--metrics-code", default="eval/metrics.py")
    parser.add_argument("--reviewer-1", required=True, help="R1 packet ZIP or completed question CSV")
    parser.add_argument("--reviewer-2", required=True, help="R2 packet ZIP or completed question CSV")
    parser.add_argument("--adjudication", help="future human adjudication JSON")
    parser.add_argument("--release", help="future signed-off freeze JSON")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", help="optional ignored plan JSON; refuses overwrite")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-input-chars", type=int, required=True)
    parser.add_argument("--max-input-tokens-per-request", type=int, required=True)
    parser.add_argument("--max-output-tokens", type=int, required=True)
    parser.add_argument("--max-api-requests", type=int, required=True)
    parser.add_argument("--max-cost-usd", required=True)
    parser.add_argument("--input-usd-per-million", required=True)
    parser.add_argument("--output-usd-per-million", required=True)
    parser.add_argument("--price-source", required=True)
    parser.add_argument("--price-date", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=45)
    args = parser.parse_args(argv)
    try:
        plan = build_plan(
            lock_path=Path(args.lock), split_path=Path(args.split),
            test_csv=Path(args.test_csv), dev_csv=Path(args.dev_csv),
            questions_path=Path(args.questions), references_path=Path(args.references),
            test_gold_path=Path(args.test_gold), metrics_path=Path(args.metrics_code),
            reviewer_1_path=Path(args.reviewer_1), reviewer_2_path=Path(args.reviewer_2),
            run_dir=Path(args.run_dir), provider=args.provider, model=args.model,
            max_input_chars=args.max_input_chars,
            max_input_tokens=args.max_input_tokens_per_request,
            max_output_tokens=args.max_output_tokens,
            max_api_requests=args.max_api_requests,
            max_cost_usd=args.max_cost_usd,
            input_usd_per_million=args.input_usd_per_million,
            output_usd_per_million=args.output_usd_per_million,
            price_source=args.price_source, price_date=args.price_date,
            timeout_seconds=args.timeout_seconds,
            release_path=Path(args.release) if args.release else None,
            adjudication_path=Path(args.adjudication) if args.adjudication else None,
        )
        if args.out:
            output = Path(args.out)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as stream:
                json.dump(plan, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        print(json.dumps(plan, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, BudgetError) as exc:
        print(f"formal preflight failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
