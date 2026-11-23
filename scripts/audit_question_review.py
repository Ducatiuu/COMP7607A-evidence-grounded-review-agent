"""Audit self-reported human review sheets without creating approvals or a freeze."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from eval.question_audit import audit_candidate_questions
from eval.questions import GoldReference, QuestionCandidate
from scripts.export_question_review import _FIELDS


_JUDGMENTS = ("wording_ok", "answerability_ok", "denominator_ok", "reference_ok")


def _read_sheet(path: Path, questions: list[QuestionCandidate],
                references: dict[str, GoldReference], audit: dict) -> tuple[list[dict[str, str]], str | None]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or len(reader.fieldnames) != len(_FIELDS) or set(reader.fieldnames) != set(_FIELDS):
            raise ValueError("review sheet columns do not match the exported template")
        rows = list(reader)
    if (len(rows) != len(questions)
            or any(None in row or any(not isinstance(value, str) for value in row.values()) for row in rows)):
        raise ValueError("review sheet row count or CSV structure is invalid")
    reviewer_ids = {row["reviewer_id"].strip() for row in rows if row["reviewer_id"].strip()}
    if len(reviewer_ids) > 1:
        raise ValueError("one review sheet contains multiple reviewer IDs")
    reviewer_id = next(iter(reviewer_ids)) if reviewer_ids else None
    for row, question in zip(rows, questions, strict=True):
        reference = references[question.question_id]
        expected = {
            "question_id": question.question_id, "pack_id": question.pack_id,
            "task_type": question.task_type, "wording": question.wording,
            "denominator_spec": question.denominator_spec or "",
            "rate_category": question.rate_category.value if question.rate_category else "",
            "questions_sha256": audit["questions_sha256"],
            "references_sha256": audit["references_sha256"],
        }
        if any(row[field] != value for field, value in expected.items()):
            raise ValueError("review sheet changed an immutable candidate field or hash")
        try:
            aligned = (json.loads(row["record_ids"]) == question.record_ids
                       and json.loads(row["expected_fields"]) == question.expected_fields
                       and json.loads(row["reference_json"]) == reference.model_dump(mode="json"))
        except (TypeError, ValueError):
            aligned = False
        if not aligned:
            raise ValueError("review sheet changed the record scope or independent reference")
        if any(row[field].strip().lower() not in {"", "yes", "no"} for field in _JUDGMENTS):
            raise ValueError("review judgments must be yes, no, or blank")
    return rows, reviewer_id


def audit_review_sheets(questions: list[QuestionCandidate], references: list[GoldReference],
                        sheet_1: Path, sheet_2: Path) -> dict:
    audit = audit_candidate_questions(questions, references)
    if audit["coverage_gaps"]:
        raise ValueError("candidate question coverage has gaps")
    by_id = {item.question_id: item for item in references}
    rows_1, reviewer_1 = _read_sheet(sheet_1, questions, by_id, audit)
    rows_2, reviewer_2 = _read_sheet(sheet_2, questions, by_id, audit)
    if reviewer_1 is not None and reviewer_2 is not None and reviewer_1 == reviewer_2:
        raise ValueError("independent review sheets must have distinct reviewer IDs")
    missing_reviewer_ids = sum(not row["reviewer_id"].strip() for rows in (rows_1, rows_2) for row in rows)
    missing = sum(not row[field].strip() for rows in (rows_1, rows_2) for row in rows for field in _JUDGMENTS)
    rejected = sum(row[field].strip().lower() == "no" for rows in (rows_1, rows_2)
                   for row in rows for field in _JUDGMENTS)
    disagreements = sum(bool(row_1[field].strip() and row_2[field].strip()
                             and row_1[field].strip().lower() != row_2[field].strip().lower())
                        for row_1, row_2 in zip(rows_1, rows_2, strict=True) for field in _JUDGMENTS)
    edits = sum(bool(row["proposed_edit"].strip()) for rows in (rows_1, rows_2) for row in rows)
    if missing or missing_reviewer_ids:
        status = "PENDING_HUMAN_REVIEW"
    elif rejected or disagreements or edits:
        status = "NEEDS_HUMAN_ADJUDICATION"
    else:
        status = "REPORTED_READY_FOR_MAINTAINER_REVIEW"
    return {"status": status, "human_review_verified": False, "frozen": False,
            "questions": len(questions), "missing_judgments": missing,
            "missing_reviewer_ids": missing_reviewer_ids,
            "rejected_judgments": rejected, "disagreements": disagreements,
            "proposed_edits": edits, "distinct_reviewer_ids_reported": bool(reviewer_1 and reviewer_2),
            "questions_sha256": audit["questions_sha256"],
            "references_sha256": audit["references_sha256"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit two local question/reference review sheets")
    parser.add_argument("--questions", default="data/processed/candidate_questions.json")
    parser.add_argument("--references", default="data/gold/candidate_references.json")
    parser.add_argument("--sheets-root", default="data/gold/question_review")
    args = parser.parse_args(argv)
    questions = [QuestionCandidate.model_validate(item) for item in
                 json.loads(Path(args.questions).read_text(encoding="utf-8"))]
    references = [GoldReference.model_validate(item) for item in
                  json.loads(Path(args.references).read_text(encoding="utf-8"))]
    question_audit = audit_candidate_questions(questions, references)
    sheet_dir = Path(args.sheets_root) / question_audit["questions_sha256"][:12]
    result = audit_review_sheets(questions, references,
                                 sheet_dir / "reviewer_1.csv", sheet_dir / "reviewer_2.csv")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "REPORTED_READY_FOR_MAINTAINER_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
