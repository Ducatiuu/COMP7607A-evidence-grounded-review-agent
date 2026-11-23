"""Explicitly gated single-question or extraction CLI for review CSV files."""

from __future__ import annotations

import argparse
import json
import os
import sys

from src.absa_service import ExtractionService
from src.data_loader import DataLoadError, dataset_fingerprint, load_csv
from src.deepseek_balance import BalanceError, require_dev_run_balance
from src.live_cost import BudgetError, CostLimitedClient, plan_cost
from src.live_runtime import conservative_request_bound, run_model_method
from src.responses_client import ResponsesClient


_KEY_NAMES = {"openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight or explicitly run model-backed review analysis")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("extract", "ask"):
        command = subcommands.add_parser(name)
        command.add_argument("--input", required=True)
        command.add_argument("--text-column", default="text")
        command.add_argument("--id-column", default="record_id")
        command.add_argument("--provider", choices=sorted(_KEY_NAMES), required=True)
        command.add_argument("--model", required=True)
        command.add_argument("--max-records", type=int, required=True)
        command.add_argument("--max-input-chars", type=int, required=True)
        command.add_argument("--max-api-requests", type=int, required=True)
        command.add_argument("--max-input-tokens-per-request", type=int, required=True)
        command.add_argument("--max-output-tokens", type=int, required=True)
        command.add_argument("--max-cost-usd", required=True)
        command.add_argument("--input-usd-per-million", required=True)
        command.add_argument("--output-usd-per-million", required=True)
        command.add_argument("--price-source", required=True)
        command.add_argument("--price-date", required=True)
        command.add_argument("--timeout-seconds", type=float, default=60)
        command.add_argument("--extraction-prompt-version", choices=("extract-v1", "extract-v2"),
                             default="extract-v2")
        command.add_argument("--query-prompt-version", choices=("query-v1", "query-v2", "query-v3"),
                             default="query-v3")
        command.add_argument("--answer-prompt-version", choices=("answer-v1", "answer-v2", "answer-v3", "answer-v4"),
                             default="answer-v4")
        command.add_argument("--decision-prompt-version", choices=("decision-v1", "decision-v2", "decision-v3"),
                             default="decision-v3")
        command.add_argument("--direct-prompt-version", choices=("direct-v2", "direct-v3"),
                             default="direct-v3")
        command.add_argument("--execute", action="store_true", help="enable real provider network calls")
    ask = subcommands.choices["ask"]
    ask.add_argument("--method", choices="abc", required=True)
    ask.add_argument("--question", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        records = load_csv(args.input, text_column=args.text_column, id_column=args.id_column)
    except (OSError, DataLoadError):
        print("CSV could not be read or validated; check the file and selected columns", file=sys.stderr)
        return 2
    try:
        if not isinstance(args.model, str) or not args.model.strip() or args.model == "mock":
            raise ValueError("a real provider model ID is required")
        if args.max_records < 1 or len(records.records) > args.max_records:
            raise ValueError("record count exceeds configured limit")
        if args.max_input_chars < 1:
            raise ValueError("positive input character limit required")
        question = args.question if args.command == "ask" else ""
        if args.command == "ask" and not question.strip():
            raise ValueError("nonempty question required")
        if sum(len(record.text) for record in records.records) + len(question) > args.max_input_chars:
            raise ValueError("source text and question exceed configured input character limit")
        bound = (conservative_request_bound(args.method, len(records.records))
                 if args.command == "ask" else 2 * len(records.records))
        if args.max_api_requests < bound:
            raise ValueError(f"request ceiling must allow the conservative {bound}-request bound")
        plan = plan_cost(
            max_requests=args.max_api_requests,
            max_input_tokens_per_request=args.max_input_tokens_per_request,
            max_output_tokens_per_request=args.max_output_tokens,
            max_cost_usd=args.max_cost_usd,
            input_usd_per_million=args.input_usd_per_million,
            output_usd_per_million=args.output_usd_per_million,
            price_source=args.price_source, price_date=args.price_date,
        )
        client = ResponsesClient(args.provider, args.model, max_output_tokens=args.max_output_tokens,
                                 timeout_seconds=args.timeout_seconds, allow_network=args.execute)
    except (ValueError, BudgetError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    preflight = {
        "provider": args.provider, "model": args.model, "command": args.command,
        "record_count": len(records.records), "dataset_sha256": dataset_fingerprint(records),
        "conservative_requests": bound, "request_ceiling": args.max_api_requests,
        "declared_worst_case_usd": str(plan.worst_case_usd),
        "cost_cap_usd": str(plan.max_cost_usd), "price_source": plan.price_source,
        "price_date": plan.price_date,
        "extraction_prompt_version": args.extraction_prompt_version,
        "query_prompt_version": args.query_prompt_version,
        "answer_prompt_version": args.answer_prompt_version,
        "decision_prompt_version": args.decision_prompt_version,
        "direct_prompt_version": args.direct_prompt_version,
    }
    if not args.execute:
        print(json.dumps({"mode": "DRY_RUN", **preflight}, ensure_ascii=False, indent=2))
        return 0
    if not os.environ.get(_KEY_NAMES[args.provider]):
        print(f"{_KEY_NAMES[args.provider]} is not set", file=sys.stderr)
        return 2
    if args.provider == "deepseek":
        try:
            require_dev_run_balance(plan.max_cost_usd)
        except (BalanceError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2

    guarded = CostLimitedClient(client, plan)
    if args.command == "ask":
        run = run_model_method(
            records, method=args.method, question=question, client=guarded, model_id=args.model,
            max_api_requests=args.max_api_requests, max_records=args.max_records,
            max_input_chars=args.max_input_chars,
            extraction_prompt_version=args.extraction_prompt_version,
            query_prompt_version=args.query_prompt_version,
            answer_prompt_version=args.answer_prompt_version,
            decision_prompt_version=args.decision_prompt_version,
            direct_prompt_version=args.direct_prompt_version,
        )
        payload = {"answer": run.answer.model_dump(mode="json"),
                   "extraction_coverage": (run.extraction_dataset.coverage.model_dump(mode="json")
                                           if run.extraction_dataset is not None else None)}
        failed = run.answer.status in {"failed", "partial"}
    else:
        extraction = ExtractionService(guarded, provider_model=args.model,
                                       prompt_version=args.extraction_prompt_version).extract(records)
        payload = {"coverage": extraction.dataset.coverage.model_dump(mode="json"),
                   "attempt_diagnostics": extraction.attempt_diagnostics,
                   "extractions": [item.model_dump(mode="json") for item in extraction.dataset.extractions]}
        failed = bool(extraction.dataset.coverage.failed_ids)
    print(json.dumps({"mode": "LIVE", **preflight,
                      "actual_requests": guarded.requests,
                      "input_tokens": guarded.input_tokens, "output_tokens": guarded.output_tokens,
                      "estimated_cost_usd": (str(guarded.estimated_cost_usd)
                                             if guarded.estimated_cost_usd is not None else None),
                      **payload}, ensure_ascii=False, indent=2))
    return 3 if failed or guarded.frozen else 0


if __name__ == "__main__":
    raise SystemExit(main())
