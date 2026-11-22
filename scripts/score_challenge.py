"""Score challenge extraction only when a separate local reference file exists."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.challenge_metrics import ChallengeReference, prediction_from_run_payload, score_challenge_predictions


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", nargs="+", required=True)
    parser.add_argument("--references", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    predictions = [prediction_from_run_payload(json.loads(Path(path).read_text(encoding="utf-8")))
                   for path in args.predictions]
    references = [ChallengeReference.model_validate(item)
                  for item in json.loads(Path(args.references).read_text(encoding="utf-8"))]
    result = score_challenge_predictions(predictions, references)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"provenance": result["provenance"], "pair_count": result["pair_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
