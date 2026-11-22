"""Offline command entry point. Real API execution is intentionally unconfigured."""

from __future__ import annotations

import argparse
import json

from src.absa_service import ExtractionService
from src.controllers import DirectLLM, DynamicAgent, FixedWorkflow, QueryParser
from src.data_loader import load_csv
from src.demo_mock import DEMO_QUESTION, mock_for_demo
from src.tools import AnalysisContext
from src.verification import Finalizer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synthetic offline ABSA demo")
    subcommands = parser.add_subparsers(dest="command", required=True)
    extract = subcommands.add_parser("extract")
    extract.add_argument("--input", required=True)
    extract.add_argument("--mock", action="store_true", required=True)
    ask = subcommands.add_parser("ask")
    ask.add_argument("--input", required=True)
    ask.add_argument("--method", choices=["a", "b", "c"], required=True)
    ask.add_argument("--question", required=True)
    ask.add_argument("--mock", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        records = load_csv(args.input)
        if args.command == "extract":
            client = mock_for_demo(records, method="extract")
            run = ExtractionService(client, provider_model="mock").extract(records)
            result = {"mode": "MOCK", "dataset": run.dataset.model_dump(mode="json"),
                      "requests": run.requests, "retries": run.retries, "cache_hits": run.cache_hits}
        else:
            client = mock_for_demo(records, method=args.method, question=args.question)
            if args.method == "a":
                answer = DirectLLM(client, "mock").run(records=records, question=args.question, question_id="demo-rate")
            elif args.method == "b":
                extraction = ExtractionService(client, provider_model="mock").extract(records)
                workflow = FixedWorkflow(QueryParser(client, "mock"), Finalizer(client, "mock"))
                answer = workflow.run(ctx=AnalysisContext(extraction.dataset), question=args.question, question_id="demo-rate")
            else:
                extraction = ExtractionService(client, provider_model="mock").extract(records)
                agent = DynamicAgent(QueryParser(client, "mock"), client, Finalizer(client, "mock"), "mock")
                answer = agent.run(ctx=AnalysisContext(extraction.dataset), question=args.question, question_id="demo-rate")
            result = {"mode": "MOCK", "answer": answer.model_dump(mode="json")}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
