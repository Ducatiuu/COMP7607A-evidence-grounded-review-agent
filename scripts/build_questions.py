"""Write local unreviewed question candidates and separate gold references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.questions import build_candidate_questions, build_gold_references
from src.semeval import CandidateSplit, GoldRecord


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build unreviewed local question/reference candidates")
    parser.add_argument("--split", default="data/processed/candidate_split.json")
    parser.add_argument("--gold", default="data/gold/test.json")
    parser.add_argument("--questions-out", default="data/processed/candidate_questions.json")
    parser.add_argument("--references-out", default="data/gold/candidate_references.json")
    args = parser.parse_args(argv)
    split = CandidateSplit.model_validate_json(Path(args.split).read_text(encoding="utf-8"))
    gold = [GoldRecord.model_validate(item) for item in json.loads(Path(args.gold).read_text(encoding="utf-8"))]
    questions = build_candidate_questions(split)
    references = build_gold_references(questions, gold)
    questions_path, refs_path = Path(args.questions_out), Path(args.references_out)
    questions_path.parent.mkdir(parents=True, exist_ok=True)
    refs_path.parent.mkdir(parents=True, exist_ok=True)
    questions_path.write_text(json.dumps([item.model_dump(mode="json") for item in questions], ensure_ascii=False, indent=2), encoding="utf-8")
    refs_path.write_text(json.dumps([item.model_dump(mode="json") for item in references], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "CANDIDATE_UNREVIEWED", "questions": len(questions), "references": len(references)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
