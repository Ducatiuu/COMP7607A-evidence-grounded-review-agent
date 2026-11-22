"""Prepare unlabeled A/B/C review items and a separate private method key."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.blind_review import export_blind_review
from eval.subsets import CandidateSubsets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs=3, required=True)
    parser.add_argument("--subsets", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    subsets = CandidateSubsets.model_validate_json(Path(args.subsets).read_text(encoding="utf-8"))
    print(json.dumps(export_blind_review(args.runs, subsets.evidence_review, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
