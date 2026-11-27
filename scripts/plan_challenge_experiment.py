"""Create a local, hash-bound Challenge plan without contacting a provider."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.run_challenge_experiment import build_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen 40-pair Challenge plan; no network")
    parser.add_argument("--pairs", default="data/challenge/final_text_2026-11-27/final_candidate_pairs.json")
    parser.add_argument("--references", default="data/gold/challenge_40_2026-11-27/references.json")
    parser.add_argument("--release", default="data/gold/challenge_40_2026-11-27/release.json")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--max-requests", type=int, default=160)
    parser.add_argument("--max-input-tokens", type=int, default=8192)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--max-cost-usd", required=True)
    parser.add_argument("--input-usd-per-million", required=True)
    parser.add_argument("--output-usd-per-million", required=True)
    parser.add_argument("--price-source", required=True)
    parser.add_argument("--price-date", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=45)
    args = parser.parse_args(argv)
    try:
        target = Path(args.out)
        if target.exists() or not str(target).startswith("outputs"):
            raise ValueError("plan output must be a new local outputs path")
        plan = build_plan(
            pairs_path=Path(args.pairs), references_path=Path(args.references),
            release_path=Path(args.release), run_dir=Path(args.run_dir),
            model=args.model, max_requests=args.max_requests,
            max_input_tokens=args.max_input_tokens, max_output_tokens=args.max_output_tokens,
            max_cost_usd=args.max_cost_usd,
            input_usd_per_million=args.input_usd_per_million,
            output_usd_per_million=args.output_usd_per_million,
            price_source=args.price_source, price_date=args.price_date,
            timeout_seconds=args.timeout_seconds)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as stream:
            json.dump(plan, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps({"status": plan["status"], "network_calls_made": 0,
                          "plan_sha256": plan["plan_sha256"], "plan_path": str(target)}))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": type(exc).__name__,
                          "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
