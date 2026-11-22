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
    parser.add_argument("--shared-extraction", help="optional verified MOCK setup artifact for B/C main")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    refs = [GoldReference.model_validate(item) for item in json.loads(Path(args.references).read_text(encoding="utf-8"))]
    summary = summarize_runs(args.runs, refs, shared_extraction_dir=args.shared_extraction)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    diagnostic = {"mode": summary["mode"], "runs": len(summary["runs"]), "paired": summary["paired"]}
    if "shared_extraction" in summary:
        diagnostic["combined_physical_requests"] = summary["shared_extraction"]["combined_physical_requests"]
    print(json.dumps(diagnostic))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
