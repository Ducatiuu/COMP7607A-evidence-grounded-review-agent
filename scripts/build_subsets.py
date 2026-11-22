"""Write deterministic, unreviewed 20/30/30 candidate subsets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.questions import QuestionCandidate
from eval.subsets import build_candidate_subsets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default="data/processed/candidate_questions.json")
    parser.add_argument("--out", default="data/processed/candidate_subsets.json")
    args = parser.parse_args(argv)
    questions = [QuestionCandidate.model_validate(item) for item in json.loads(Path(args.questions).read_text(encoding="utf-8"))]
    result = build_candidate_subsets(questions)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps({"status": result.status, "repeats": len(result.repeats),
                      "gold_diagnostic": len(result.gold_diagnostic),
                      "verification_ablation": len(result.verification_ablation),
                      "evidence_review": len(result.evidence_review)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
