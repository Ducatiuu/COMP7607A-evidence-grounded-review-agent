"""Read-only preflight for a bounded Train-derived A/B/C development pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from eval.questions import QuestionCandidate
from src.data_loader import load_csv
from src.live_cost import plan_cost
from src.live_runtime import conservative_request_bound
from src.semeval import CandidateSplit


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_plan(*, manifest_path: Path, csv_path: Path, questions_path: Path,
               references_path: Path, split_path: Path, run_dir: Path,
               provider: str, model: str, max_input_chars: int,
               max_input_tokens: int, max_output_tokens: int, max_cost_usd: str,
               input_usd_per_million: str, output_usd_per_million: str,
               price_source: str, price_date: str, timeout_seconds: float) -> dict:
    if run_dir.exists():
        raise ValueError("run directory already exists; do not risk repeating a prior API run")
    if provider != "deepseek" or model != "deepseek-flash":
        raise ValueError("pilot provider and exact model must match the verified DeepSeek configuration")
    if not 0 < timeout_seconds <= 120:
        raise ValueError("timeout must be positive and at most 120 seconds")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    split = CandidateSplit.model_validate_json(split_path.read_text(encoding="utf-8"))
    records = load_csv(csv_path)
    questions = [QuestionCandidate.model_validate(item) for item in
                 json.loads(questions_path.read_text(encoding="utf-8"))]
    ids = [item.record_id for item in records.records]
    qids = [item.question_id for item in questions]
    if (manifest.get("status") != "DEV_PILOT_CANDIDATE_UNREVIEWED"
            or manifest.get("human_review_complete") is not False
            or manifest.get("source_split_sha256") != split.manifest_sha256
            or manifest.get("source_train_sha256") != split.train_sha256
            or manifest.get("record_ids") != ids
            or manifest.get("question_ids") != qids
            or manifest.get("pilot_csv_sha256") != _digest(csv_path)
            or manifest.get("questions_sha256") != _digest(questions_path)
            or manifest.get("references_sha256") != _digest(references_path)):
        raise ValueError("pilot candidate hashes, IDs or provenance do not match")
    if (len(ids) != 30 or len(qids) != 10 or len(set(ids)) != 30 or len(set(qids)) != 10
            or not set(ids).issubset(split.dev_ids) or set(ids) & set(split.test_ids)
            or any(question.record_ids != ids or question.pack_id != "DEV-PILOT"
                   or question.status != "CANDIDATE_UNREVIEWED" for question in questions)):
        raise ValueError("pilot requires the same 30 Train-derived records for all ten questions")
    source_chars = sum(len(item.text) for item in records.records)
    max_question_chars = max(len(item.wording) for item in questions)
    if type(max_input_chars) is not int or source_chars + max_question_chars > max_input_chars:
        raise ValueError("pilot source/question character limit is too small")

    extraction_bound = 2 * len(ids)
    method_bounds = {method: conservative_request_bound(method, len(ids), prepared_extraction=True) * len(qids)
                     for method in ("a", "b", "c")}
    request_ceiling = extraction_bound + sum(method_bounds.values())
    cost = plan_cost(max_requests=request_ceiling,
                     max_input_tokens_per_request=max_input_tokens,
                     max_output_tokens_per_request=max_output_tokens,
                     max_cost_usd=max_cost_usd,
                     input_usd_per_million=input_usd_per_million,
                     output_usd_per_million=output_usd_per_million,
                     price_source=price_source, price_date=price_date)
    plan = {
        "status": "DRY_RUN_APPROVAL_REQUIRED", "network_calls_made": 0,
        "execution_runner_ready": True,
        "provider": provider, "model": model, "reasoning_effort": "none",
        "extraction_prompt_version": "extract-v2",
        "query_prompt_version": "query-v3",
        "answer_prompt_version": "answer-v4",
        "decision_prompt_version": "decision-v3",
        "direct_prompt_version": "direct-v3",
        "methods": ["a", "b", "c"], "concurrency": 1,
        "transport_retries": 0, "timeout_seconds": timeout_seconds,
        "data_scope": "TRAIN_DERIVED_DEV_ONLY", "candidate_review_complete": False,
        "pilot_manifest_sha256": _digest(manifest_path),
        "split_sha256": _digest(split_path),
        "pilot_csv_sha256": _digest(csv_path),
        "questions_sha256": _digest(questions_path),
        "references_sha256": _digest(references_path),
        "record_count": len(ids), "question_count": len(qids),
        "source_review_chars": source_chars, "max_question_chars": max_question_chars,
        "max_input_chars": max_input_chars,
        "shared_extraction_request_bound": extraction_bound,
        "method_request_bounds": method_bounds, "max_api_requests": request_ceiling,
        "max_input_tokens_per_request": max_input_tokens,
        "max_output_tokens_per_request": max_output_tokens,
        "max_cost_usd": str(cost.max_cost_usd),
        "declared_worst_case_usd": str(cost.worst_case_usd),
        "input_usd_per_million": str(cost.input_usd_per_million),
        "output_usd_per_million": str(cost.output_usd_per_million),
        "price_source": cost.price_source, "price_date": cost.price_date,
        "planned_run_directory": str(run_dir),
    }
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    plan["plan_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight an unrun 30-record/10-question A/B/C dev pilot")
    parser.add_argument("--manifest", default="data/processed/dev_pilot/manifest.json")
    parser.add_argument("--csv", default="data/processed/dev_pilot/pilot.csv")
    parser.add_argument("--questions", default="data/processed/dev_pilot/questions.json")
    parser.add_argument("--references", default="data/gold/dev_pilot/references.json")
    parser.add_argument("--split", default="data/processed/candidate_split.json")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", help="optional ignored plan JSON; refuses to overwrite")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-input-chars", type=int, required=True)
    parser.add_argument("--max-input-tokens-per-request", type=int, required=True)
    parser.add_argument("--max-output-tokens", type=int, required=True)
    parser.add_argument("--max-cost-usd", required=True)
    parser.add_argument("--input-usd-per-million", required=True)
    parser.add_argument("--output-usd-per-million", required=True)
    parser.add_argument("--price-source", required=True)
    parser.add_argument("--price-date", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=45)
    args = parser.parse_args(argv)
    plan = build_plan(
        manifest_path=Path(args.manifest), csv_path=Path(args.csv),
        questions_path=Path(args.questions), references_path=Path(args.references),
        split_path=Path(args.split), run_dir=Path(args.run_dir),
        provider=args.provider, model=args.model, max_input_chars=args.max_input_chars,
        max_input_tokens=args.max_input_tokens_per_request,
        max_output_tokens=args.max_output_tokens, max_cost_usd=args.max_cost_usd,
        input_usd_per_million=args.input_usd_per_million,
        output_usd_per_million=args.output_usd_per_million,
        price_source=args.price_source, price_date=args.price_date,
        timeout_seconds=args.timeout_seconds,
    )
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(plan, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print(json.dumps(plan, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
