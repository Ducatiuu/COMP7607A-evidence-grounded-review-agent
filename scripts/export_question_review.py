"""Create separate, blank human review sheets for actual candidate questions."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from eval.question_audit import audit_candidate_questions
from eval.questions import GoldReference, QuestionCandidate


_FIELDS = [
    "question_id", "pack_id", "task_type", "wording", "record_ids",
    "expected_fields", "denominator_spec", "rate_category", "reference_json",
    "questions_sha256", "references_sha256", "reviewer_id", "wording_ok",
    "answerability_ok", "denominator_ok", "reference_ok", "proposed_edit", "notes",
]
_BLANK_FIELDS = ["reviewer_id", "wording_ok", "answerability_ok", "denominator_ok",
                 "reference_ok", "proposed_edit", "notes"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export blank local question/reference review sheets")
    parser.add_argument("--questions", default="data/processed/candidate_questions.json")
    parser.add_argument("--references", default="data/gold/candidate_references.json")
    parser.add_argument("--out", default="data/gold/question_review")
    parser.add_argument("--expected-packs", type=int, default=20)
    args = parser.parse_args(argv)

    questions = [QuestionCandidate.model_validate(item) for item in
                 json.loads(Path(args.questions).read_text(encoding="utf-8"))]
    references = [GoldReference.model_validate(item) for item in
                  json.loads(Path(args.references).read_text(encoding="utf-8"))]
    audit = audit_candidate_questions(questions, references,
                                      expected_packs=args.expected_packs)
    if audit["coverage_gaps"]:
        raise ValueError("candidate coverage gaps must be resolved before human review export")

    output = Path(args.out) / audit["questions_sha256"][:12]
    targets = [output / "reviewer_1.csv", output / "reviewer_2.csv"]
    if any(path.exists() for path in targets):
        print("review sheet already exists; existing human work was preserved", file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=True)
    by_id = {reference.question_id: reference for reference in references}
    for target in targets:
        with target.open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=_FIELDS)
            writer.writeheader()
            for question in questions:
                row = {
                    "question_id": question.question_id,
                    "pack_id": question.pack_id,
                    "task_type": question.task_type,
                    "wording": question.wording,
                    "record_ids": json.dumps(question.record_ids),
                    "expected_fields": json.dumps(question.expected_fields),
                    "denominator_spec": question.denominator_spec or "",
                    "rate_category": question.rate_category.value if question.rate_category else "",
                    "reference_json": by_id[question.question_id].model_dump_json(),
                    "questions_sha256": audit["questions_sha256"],
                    "references_sha256": audit["references_sha256"],
                }
                row.update({field: "" for field in _BLANK_FIELDS})
                writer.writerow(row)
    print(json.dumps({"status": "PENDING_HUMAN_REVIEW", "questions": len(questions),
                      "review_sheets": [str(path) for path in targets]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
