"""Write a candidate coverage audit; no automatic human approval or freeze."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.question_audit import audit_candidate_questions
from eval.questions import GoldReference, QuestionCandidate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default="data/processed/candidate_questions.json")
    parser.add_argument("--references", default="data/gold/candidate_references.json")
    parser.add_argument("--out", default="data/processed/candidate_question_audit.json")
    parser.add_argument("--expected-packs", type=int, default=20)
    parser.add_argument("--expected-pack-size", type=int, default=30)
    args = parser.parse_args(argv)
    questions = [QuestionCandidate.model_validate(item) for item in json.loads(Path(args.questions).read_text(encoding="utf-8"))]
    references = [GoldReference.model_validate(item) for item in json.loads(Path(args.references).read_text(encoding="utf-8"))]
    audit = audit_candidate_questions(questions, references, expected_packs=args.expected_packs,
                                      expected_pack_size=args.expected_pack_size)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps({"status": audit["status"], "coverage_gaps": audit["coverage_gaps"],
                      "question_count": audit["question_count"]}))
    return 0 if not audit["coverage_gaps"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
