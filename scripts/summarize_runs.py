"""Score run rows against a separate local gold file; never publish MOCK as findings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.questions import GoldReference
from eval.report import summarize_runs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", required=True)
    parser.add_argument("--references", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    refs = [GoldReference.model_validate(item) for item in json.loads(Path(args.references).read_text(encoding="utf-8"))]
    summary = summarize_runs(args.runs, refs)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"mode": summary["mode"], "runs": len(summary["runs"]), "paired": summary["paired"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
