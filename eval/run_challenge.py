"""Synthetic extraction-only challenge dry-run."""

from __future__ import annotations

import argparse
import json

from .challenge import run_synthetic_challenge


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default="data/demo/challenge_candidate.json")
    parser.add_argument("--out", default="outputs/runs/demo/challenge")
    parser.add_argument("--mock", action="store_true", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run_synthetic_challenge(args.candidate, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
