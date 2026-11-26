"""Read-only Stage 4 audit. A report from this module is never an execution release."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from eval.question_audit import TASK_TYPES, audit_candidate_questions
from eval.questions import GoldReference, QuestionCandidate
from scripts.audit_question_review import _JUDGMENTS, _read_sheet
from scripts.plan_formal_experiment import build_plan
from src.data_loader import load_csv
from src.semeval import CandidateSplit


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_items(path: Path, model: type) -> list:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} must contain a list")
    return [model.model_validate(row) for row in raw]


def _review_rows(path: Path, questions: list[QuestionCandidate],
                 references: list[GoldReference], audit: dict, reviewer_id: str) -> list[dict[str, str]]:
    rows, reported_id = _read_sheet(path, questions,
                                    {ref.question_id: ref for ref in references}, audit)
    if reported_id != reviewer_id or any(row["reviewer_id"].strip() != reviewer_id for row in rows):
        raise ValueError(f"{reviewer_id} reviewer identity is incomplete")
    if any(row[field].strip().lower() not in {"yes", "no"}
           for row in rows for field in _JUDGMENTS):
        raise ValueError(f"{reviewer_id} has incomplete judgments")
    return rows


def assess_decisions(queue: list[dict], attention_ids: set[str],
                     original_q: dict[str, QuestionCandidate],
                     original_r: dict[str, GoldReference],
                     final_q: dict[str, QuestionCandidate],
                     final_r: dict[str, GoldReference]) -> list[str]:
    """Return unresolved human or version questions; do not infer approval."""
    blockers: list[str] = []
    if len(queue) != len({row.get("question_id") for row in queue}) or (
            {row.get("question_id") for row in queue} != attention_ids):
        blockers.append("adjudication queue does not cover exactly the flagged questions")
    by_id = {row.get("question_id"): row for row in queue}
    for qid in sorted(attention_ids):
        row = by_id.get(qid)
        if row is None:
            blockers.append(f"{qid}: missing adjudication row")
            continue
        if any(not row.get(field) for field in
               ("final_decision", "decision_reason", "adjudicator", "adjudicated_at")):
            blockers.append(f"{qid}: human adjudication is incomplete")
            continue
        decision = row["final_decision"]
        if decision.startswith("retain_"):
            if final_q[qid] != original_q[qid] or final_r[qid] != original_r[qid]:
                blockers.append(f"{qid}: retained question/reference differs from reviewed candidate")
        elif decision.startswith("revise_"):
            if final_q[qid] == original_q[qid]:
                blockers.append(f"{qid}: approved wording revision is absent")
            if (not row.get("final_question_wording")
                    or final_q[qid].wording != row["final_question_wording"]):
                blockers.append(f"{qid}: revised wording does not match the owner decision")
            if final_r[qid] != original_r[qid] and not row.get("final_reference_confirmed"):
                blockers.append(f"{qid}: changed reference lacks explicit human confirmation")
            if not row.get("revised_question_confirmed"):
                blockers.append(f"{qid}: revised question has no final human confirmation")
        else:
            blockers.append(f"{qid}: unrecognized adjudication decision")
    for qid in sorted(set(final_q) - attention_ids):
        if final_q[qid] != original_q[qid] or final_r[qid] != original_r[qid]:
            blockers.append(f"{qid}: unadjudicated question/reference was changed")
    return blockers


def audit_freeze(*, root: Path, reviewer_1: Path, reviewer_2: Path,
                 adjudication_queue: Path, adjudication_status: Path,
                 final_questions: Path, final_references: Path,
                 versioned_release: bool = False) -> dict:
    """Check real local materials without making a frozen or signed release."""
    lock_path = root / "configs/formal_24_candidate.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    sources = {
        "split": root / "data/processed/candidate_split.json",
        "test_csv": root / "data/processed/test.csv",
        "dev_csv": root / "data/processed/dev.csv",
        "questions": root / "data/processed/candidate_questions.json",
        "references": root / "data/gold/candidate_references.json",
        "test_gold": root / "data/gold/test.json",
        "metrics_code": root / "eval/metrics.py",
    }
    source_hashes = {name: file_sha(path) for name, path in sources.items()}
    if source_hashes != lock["source_sha256"]:
        raise ValueError("original locked source hash mismatch")
    original_all_q = read_items(sources["questions"], QuestionCandidate)
    original_all_r = read_items(sources["references"], GoldReference)
    packs = lock["pack_ids"]
    original_q = [q for q in original_all_q if q.pack_id in packs]
    ids = lock["question_ids"]
    original_r = [r for r in original_all_r if r.question_id in ids]
    original_audit = audit_candidate_questions(original_q, original_r, expected_packs=4)
    if (original_audit["questions_sha256"] != lock["selected_questions_sha256"]
            or original_audit["references_sha256"] != lock["selected_references_sha256"]):
        raise ValueError("reviewed subset hash mismatch")
    rows_1 = _review_rows(reviewer_1, original_q, original_r, original_audit, "R1")
    rows_2 = _review_rows(reviewer_2, original_q, original_r, original_audit, "R2")
    attention = {left["question_id"] for left, right in zip(rows_1, rows_2, strict=True)
                 if any(left[key].strip().lower() != right[key].strip().lower()
                        or left[key].strip().lower() == "no"
                        or right[key].strip().lower() == "no" for key in _JUDGMENTS)
                 or left["proposed_edit"].strip() or right["proposed_edit"].strip()
                 or left["notes"].strip() or right["notes"].strip()}
    final_q_list = read_items(final_questions, QuestionCandidate)
    final_r_list = read_items(final_references, GoldReference)
    final_audit = audit_candidate_questions(final_q_list, final_r_list, expected_packs=4)
    if ([q.question_id for q in final_q_list] != ids
            or [r.question_id for r in final_r_list] != ids
            or final_audit["pack_issues"] or final_audit["pack_scope_issues"]
            or final_audit["cross_pack_overlap"]
            or final_audit["task_type_counts"] != {kind: 4 for kind in sorted(TASK_TYPES)}):
        raise ValueError("final draft does not have the locked 4 Pack / 24 question structure")
    original_q_by_id = {q.question_id: q for q in original_q}
    original_r_by_id = {r.question_id: r for r in original_r}
    final_q_by_id = {q.question_id: q for q in final_q_list}
    final_r_by_id = {r.question_id: r for r in final_r_list}
    if any(final_q_by_id[qid].record_ids != original_q_by_id[qid].record_ids
           or final_q_by_id[qid].task_type != original_q_by_id[qid].task_type
           for qid in ids):
        raise ValueError("final draft changed a locked Pack scope or task type")
    split = CandidateSplit.model_validate_json(sources["split"].read_text(encoding="utf-8"))
    test = load_csv(sources["test_csv"], preserve_explicit_ids=True)
    dev = load_csv(sources["dev_csv"], preserve_explicit_ids=True)
    selected_records = [rid for pack in packs for rid in split.packs[int(pack[1:]) - 1]]
    if (len(test.records) != 600 or len(dev.records) != 150
            or len(selected_records) != 120 or len(set(selected_records)) != 120
            or set(selected_records) & {r.record_id for r in dev.records}
            or any(final_q_by_id[qid].record_ids != split.packs[int(final_q_by_id[qid].pack_id[1:]) - 1]
                   for qid in ids)):
        raise ValueError("final draft violates test/development isolation or Pack scope")
    queue = json.loads(adjudication_queue.read_text(encoding="utf-8"))
    status = json.loads(adjudication_status.read_text(encoding="utf-8"))
    if (not isinstance(queue, list) or any(not isinstance(row, dict) for row in queue)
            or not isinstance(status, dict)):
        raise ValueError("adjudication artifacts have invalid structure")
    expected_sheet_hashes = {reviewer_1.name: file_sha(reviewer_1), reviewer_2.name: file_sha(reviewer_2)}
    if status.get("source_review_sheets_sha256") != expected_sheet_hashes:
        raise ValueError("adjudication status is not bound to these review sheets")
    if status.get("owner_queue_sha256") != file_sha(adjudication_queue):
        raise ValueError("adjudication status is not bound to this owner queue")
    queue_by_id = {row.get("question_id"): row for row in queue}
    for qid in attention:
        row = queue_by_id.get(qid)
        if row is None:
            continue
        original_question = original_q_by_id[qid]
        original_reference = original_r_by_id[qid]
        if (row.get("pack_id") != original_question.pack_id
                or row.get("task_type") != original_question.task_type
                or row.get("wording") != original_question.wording
                or row.get("candidate_reference") != original_reference.model_dump(mode="json")):
            raise ValueError(f"{qid}: adjudication context differs from reviewed candidate")
        for slot, sheet_row in (("R1", rows_1[ids.index(qid)]),
                                ("R2", rows_2[ids.index(qid)])):
            fields = (*_JUDGMENTS, "proposed_edit", "notes")
            if any(row.get("reviewers", {}).get(slot, {}).get(field) != sheet_row[field]
                   for field in fields):
                raise ValueError(f"{qid}: owner queue changed a reviewer opinion")
    blockers = assess_decisions(queue, attention, original_q_by_id, original_r_by_id,
                                final_q_by_id, final_r_by_id)
    decided = {row.get("question_id") for row in queue if row.get("final_decision")}
    if set(status.get("resolved_question_ids", [])) != decided:
        blockers.append("adjudication status does not match the recorded owner decisions")
    # The current Stage 1 lock and R1/R2 sheets bind the original wording, not
    # revised questions. A new versioned release contract is required first.
    changed_q = [qid for qid in ids if final_q_by_id[qid] != original_q_by_id[qid]]
    changed_r = [qid for qid in ids if final_r_by_id[qid] != original_r_by_id[qid]]
    if (changed_q or changed_r) and not versioned_release:
        blockers.append("Stage 1 lock and reviewer sheets bind original, not revised, materials")
    if any(ref.status != "CANDIDATE_UNREVIEWED" for ref in final_r_list):
        raise ValueError("final draft reference status was changed without a release")
    if not versioned_release:
        blockers.append("final reference file has no human-confirmed signed release")
        blockers.append("formal API price, budget and separate live authorization are not reconfirmed")
    return {
        "status": "BLOCKED_NOT_FROZEN", "execution_permitted": False,
        "network_calls_made": 0, "formal_scores_generated": False,
        "pack_ids": packs, "question_ids": ids,
        "review": {"R1_rows": len(rows_1), "R2_rows": len(rows_2),
                   "attention_question_ids": sorted(attention),
                   "all_judgments_complete": True},
        "changed_question_ids": changed_q, "changed_reference_ids": changed_r,
        "selected_record_count": len(selected_records),
        "task_type_counts": final_audit["task_type_counts"],
        "coverage_gaps_after_revision": final_audit["coverage_gaps"],
        "hashes": {"lock": file_sha(lock_path), **source_hashes,
                   "reviewer_1": file_sha(reviewer_1), "reviewer_2": file_sha(reviewer_2),
                   "adjudication_queue": file_sha(adjudication_queue),
                   "adjudication_status": file_sha(adjudication_status),
                   "final_draft_questions": file_sha(final_questions),
                   "final_draft_references": file_sha(final_references),
                   "selected_final_questions": final_audit["questions_sha256"],
                   "selected_final_references": final_audit["references_sha256"]},
        "model": "deepseek-flash", "provider": "deepseek",
        "prompt_versions": lock["prompt_versions"],
        "scoring_rule_version": lock["scoring_rule_version"],
        "blockers": blockers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only formal freeze readiness audit; no API calls")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--reviewer-1", type=Path, required=True)
    parser.add_argument("--reviewer-2", type=Path, required=True)
    parser.add_argument("--adjudication-queue", type=Path, required=True)
    parser.add_argument("--adjudication-status", type=Path, required=True)
    parser.add_argument("--final-questions", type=Path, required=True)
    parser.add_argument("--final-references", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = audit_freeze(root=args.root, reviewer_1=args.reviewer_1,
                              reviewer_2=args.reviewer_2,
                              adjudication_queue=args.adjudication_queue,
                              adjudication_status=args.adjudication_status,
                              final_questions=args.final_questions,
                              final_references=args.final_references)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps({"status": report["status"], "blockers": report["blockers"],
                          "out": str(args.out)}, ensure_ascii=False))
        return 2 if report["blockers"] else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"freeze readiness audit refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
