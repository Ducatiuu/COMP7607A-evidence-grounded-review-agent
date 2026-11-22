"""Public offline entry point for the synthetic demo run ledger."""

from __future__ import annotations

import argparse
import hashlib
import json

from src.data_loader import dataset_fingerprint, load_csv
from src.demo_mock import DEMO_QUESTION, run_demo_method
from .runner import RunConfig, RunTask, run_tasks


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Append-only MOCK experiment dry-run")
    parser.add_argument("--method", choices=["a", "b", "c"], required=True)
    parser.add_argument("--split", choices=["demo", "dev", "test"], default="demo")
    parser.add_argument("--condition", choices=["main", "repeats", "gold", "ablation", "challenge"], default="main")
    parser.add_argument("--mock", action="store_true", required=True)
    parser.add_argument("--out")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--max-api-requests", type=int)
    args = parser.parse_args(argv)
    if args.split != "demo":
        parser.error("only synthetic demo is configured; licensed dev/test files and live model are not available")
    if args.condition not in {"main", "repeats"}:
        parser.error("this condition is pending the Phase 7A offline branch implementation")
    records = load_csv("data/demo/core.csv")
    repeats = [1, 2] if args.condition == "repeats" else [0]
    tasks = [RunTask(question_id="demo-rate", pack_id="demo", question=DEMO_QUESTION, repeat_index=index) for index in repeats]
    question_hash = hashlib.sha256(json.dumps({"question_id": "demo-rate", "question": DEMO_QUESTION, "pack_id": "demo"}, sort_keys=True).encode("utf-8")).hexdigest()
    config = RunConfig(
        method=args.method, split="demo", condition=args.condition,
        dataset_sha256=dataset_fingerprint(records), question_manifest_sha256=question_hash,
        model_id="mock", prompt_version="demo-mock-v1", mock=True,
        max_api_requests=args.max_api_requests,
        estimated_requests_per_task={"a": 1, "b": 11, "c": 15}[args.method] if args.max_api_requests else None,
    )

    def execute(task: RunTask):
        answer, _ = run_demo_method(records, method=args.method, question=task.question, question_id=task.question_id)
        return answer

    summary = run_tasks(config, tasks, args.out or f"outputs/runs/demo/{args.method}/{args.condition}", execute, retry_failed=args.retry_failed)
    print(summary.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
