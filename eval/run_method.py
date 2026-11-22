"""Public offline entry point for the synthetic demo run ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path

from src.data_loader import dataset_fingerprint, load_csv
from src.demo_mock import DEMO_QUESTION, run_demo_method
from src.llm_telemetry import RecordingLLMClient
from src.semeval import GoldRecord
from .conditions import gold_substitution_dataset
from .runner import RunConfig, RunTask, run_tasks
from .shared_extraction import load_shared_extraction


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Append-only MOCK experiment dry-run")
    parser.add_argument("--method", choices=["a", "b", "c"], required=True)
    parser.add_argument("--split", choices=["demo", "dev", "test"], default="demo")
    parser.add_argument("--condition", choices=["main", "repeats", "gold", "ablation", "challenge"], default="main")
    parser.add_argument("--mock", action="store_true", required=True)
    parser.add_argument("--out")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--max-api-requests", type=int)
    parser.add_argument("--shared-extraction", help="verified MOCK extraction artifact directory for B/C")
    args = parser.parse_args(argv)
    if args.split != "demo":
        parser.error("only synthetic demo is configured; licensed dev/test files and live model are not available")
    if args.condition == "challenge":
        parser.error("challenge is an extraction-only run; use python -m eval.run_challenge")
    if args.condition == "gold" and args.method == "a":
        parser.error("gold substitution is defined for Methods B and C only")
    if args.condition == "ablation" and args.method != "c":
        parser.error("verification ablation is defined for Method C only")
    if args.shared_extraction and (args.method == "a" or args.condition == "gold"):
        parser.error("shared predicted extraction is defined only for B/C non-gold runs")
    records = load_csv("data/demo/core.csv")
    extraction_dataset = None
    condition_artifact_sha256 = None
    if args.shared_extraction:
        extraction_dataset, condition_artifact_sha256, _ = load_shared_extraction(records, args.shared_extraction)
    if args.condition == "gold":
        gold_path = Path("data/demo/core_gold.json")
        raw_gold = gold_path.read_bytes()
        condition_artifact_sha256 = hashlib.sha256(raw_gold).hexdigest()
        gold = [GoldRecord.model_validate(item) for item in json.loads(raw_gold)]
        extraction_dataset = gold_substitution_dataset(records, gold, source_sha256=condition_artifact_sha256)
    repeats = [1, 2] if args.condition == "repeats" else [0]
    tasks = [RunTask(question_id="demo-rate", pack_id="demo", question=DEMO_QUESTION, repeat_index=index) for index in repeats]
    question_hash = hashlib.sha256(json.dumps({"question_id": "demo-rate", "question": DEMO_QUESTION, "pack_id": "demo"}, sort_keys=True).encode("utf-8")).hexdigest()
    config = RunConfig(
        method=args.method, split="demo", condition=args.condition,
        dataset_sha256=dataset_fingerprint(records), question_manifest_sha256=question_hash,
        condition_artifact_sha256=condition_artifact_sha256,
        model_id="mock", prompt_version="demo-mock-v1", mock=True,
        max_api_requests=args.max_api_requests,
        estimated_requests_per_task={"a": 1, "b": 11, "c": 15}[args.method] if args.max_api_requests else None,
    )

    output_dir = Path(args.out or f"outputs/runs/demo/{args.method}/{args.condition}")

    def execute(task: RunTask):
        def instrument(client):
            return RecordingLLMClient(delegate=client, output_path=output_dir / "model_calls.jsonl",
                                      run_id=str(uuid.uuid4()), configured_model="mock", config_sha256=config.fingerprint,
                                      method=args.method, question_id=task.question_id,
                                      repeat_index=task.repeat_index, record_content=True)

        answer, _ = run_demo_method(records, method=args.method, question=task.question, question_id=task.question_id,
                                    extraction_dataset=extraction_dataset, verify_outputs=args.condition != "ablation",
                                    client_wrapper=instrument)
        return answer

    summary = run_tasks(config, tasks, output_dir, execute, retry_failed=args.retry_failed)
    print(summary.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
