"""One-shot, hash-bound A/B/C dev pilot. No network without --execute."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from eval.questions import QuestionCandidate
from scripts.plan_dev_pilot import build_plan
from src.absa_service import ExtractionService
from src.data_loader import load_csv
from src.deepseek_balance import BalanceError, require_dev_run_balance
from src.live_cost import CostLimitedClient, plan_cost
from src.live_runtime import conservative_request_bound, run_model_method
from src.llm_client import LLMClient, LLMRequest, LLMResponse
from src.responses_client import ResponsesClient


def _durable_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _append_json(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@dataclass
class CallRecorder:
    delegate: LLMClient
    path: Path
    calls: int = 0
    method: str | None = None
    question_id: str | None = None

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        call_id = self.calls
        event = {"call_id": call_id, "stage": request.stage, "method": self.method,
                 "question_id": self.question_id}
        # Persist intent before the transport call; a crash leaves an unmatched begin.
        _append_json(self.path, {"event": "begin", **event})
        try:
            response = self.delegate.complete_json(request)
        except Exception:
            _append_json(self.path, {"event": "end", **event, "outcome": "error"})
            raise
        _append_json(self.path, {"event": "end", **event, "outcome": "response",
                                  "input_tokens": response.input_tokens,
                                  "output_tokens": response.output_tokens})
        return response


@dataclass
class _GuardProxy:
    """Let each method have a local bound while sharing one global cost gate."""

    delegate: CostLimitedClient

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        return self.delegate.complete_json(request)


def checked_plan(plan_path: Path, *, manifest_path: Path, csv_path: Path,
                 questions_path: Path, references_path: Path, split_path: Path) -> dict:
    saved = json.loads(plan_path.read_text(encoding="utf-8"))
    if saved.get("status") != "DRY_RUN_APPROVAL_REQUIRED" or saved.get("execution_runner_ready") is not True:
        raise ValueError("pilot plan is not ready for the one-shot runner")
    expected = build_plan(
        manifest_path=manifest_path, csv_path=csv_path, questions_path=questions_path,
        references_path=references_path, split_path=split_path,
        run_dir=Path(saved["planned_run_directory"]), provider=saved["provider"], model=saved["model"],
        max_input_chars=saved["max_input_chars"],
        max_input_tokens=saved["max_input_tokens_per_request"],
        max_output_tokens=saved["max_output_tokens_per_request"],
        max_cost_usd=saved["max_cost_usd"],
        input_usd_per_million=saved["input_usd_per_million"],
        output_usd_per_million=saved["output_usd_per_million"],
        price_source=saved["price_source"], price_date=saved["price_date"],
        timeout_seconds=saved["timeout_seconds"],
    )
    if saved != expected:
        raise ValueError("saved pilot plan differs from current inputs or configuration")
    return expected


def run_pilot(plan: dict, *, csv_path: Path, questions_path: Path,
              client: LLMClient) -> dict:
    """Execute a prechecked plan once with an injected provider or offline fake."""
    run_dir = Path(plan["planned_run_directory"])
    run_dir.mkdir(parents=True, exist_ok=False)
    _durable_json(run_dir / "run_manifest.json", {
        "status": "IN_PROGRESS", "plan_sha256": plan["plan_sha256"],
        "model": plan["model"], "data_scope": plan["data_scope"],
        "candidate_review_complete": plan["candidate_review_complete"],
    })
    records = load_csv(csv_path)
    questions = [QuestionCandidate.model_validate(item) for item in
                 json.loads(questions_path.read_text(encoding="utf-8"))]
    cost_plan = plan_cost(
        max_requests=plan["max_api_requests"],
        max_input_tokens_per_request=plan["max_input_tokens_per_request"],
        max_output_tokens_per_request=plan["max_output_tokens_per_request"],
        max_cost_usd=plan["max_cost_usd"],
        input_usd_per_million=plan["input_usd_per_million"],
        output_usd_per_million=plan["output_usd_per_million"],
        price_source=plan["price_source"], price_date=plan["price_date"],
    )
    recorder = CallRecorder(client, run_dir / "calls.jsonl")
    guarded = CostLimitedClient(recorder, cost_plan)
    proxy = _GuardProxy(guarded)
    completed = 0
    answer_status_counts: dict[str, int] = {}
    unexpected_status_count = 0
    status = "INTERRUPTED"
    reason = None
    coverage = None
    try:
        recorder.method = "shared_extraction"
        extraction = ExtractionService(proxy, provider_model=plan["model"],
                                       prompt_version=plan["extraction_prompt_version"]).extract(records)
        _durable_json(run_dir / "extractions.json", extraction.dataset.model_dump(mode="json"))
        coverage = extraction.dataset.coverage.model_dump(mode="json")
        _append_json(run_dir / "events.jsonl", {"event": "extraction_complete",
                                                  "requests": extraction.requests,
                                                  "coverage": coverage})
        if guarded.frozen:
            reason = "GLOBAL_GATE_FROZEN"
        elif coverage["failed_ids"]:
            reason = "EXTRACTION_COVERAGE_INCOMPLETE"
        else:
            for question in questions:
                for method in ("a", "b", "c"):
                    bound = conservative_request_bound(method, len(records.records),
                                                       prepared_extraction=True)
                    if guarded.requests + bound > cost_plan.max_requests:
                        reason = "REQUEST_CEILING_REMAINING_TOO_SMALL"
                        break
                    if guarded.frozen:
                        reason = "GLOBAL_GATE_FROZEN"
                        break
                    recorder.method = method
                    recorder.question_id = question.question_id
                    before = guarded.requests
                    try:
                        result = run_model_method(
                            records, method=method, question=question.wording,
                            question_id=question.question_id, client=proxy,
                            model_id=plan["model"], max_api_requests=bound,
                            max_records=plan["record_count"],
                            max_input_chars=plan["max_input_chars"],
                            extraction_dataset=(None if method == "a" else extraction.dataset),
                            extraction_prompt_version=plan["extraction_prompt_version"],
                            query_prompt_version=plan["query_prompt_version"],
                            answer_prompt_version=plan["answer_prompt_version"],
                        )
                        row = {"question_id": question.question_id, "method": method,
                               "requests": guarded.requests - before,
                               "answer": result.answer.model_dump(mode="json")}
                    except Exception:
                        row = {"question_id": question.question_id, "method": method,
                               "requests": guarded.requests - before,
                               "execution_error": "UNEXPECTED_RUNTIME_ERROR"}
                        _append_json(run_dir / "results.jsonl", row)
                        reason = "UNEXPECTED_RUNTIME_ERROR"
                        break
                    _append_json(run_dir / "results.jsonl", row)
                    completed += 1
                    answer_status = result.answer.status
                    answer_status_counts[answer_status] = answer_status_counts.get(answer_status, 0) + 1
                    expected_status = "insufficient_info" if question.task_type == "insufficient_info" else "ok"
                    if answer_status != expected_status:
                        unexpected_status_count += 1
                    if guarded.frozen:
                        reason = "GLOBAL_GATE_FROZEN"
                        break
                if reason:
                    break
        status = "COMPLETE" if reason is None and completed == len(questions) * 3 else "PARTIAL"
    finally:
        summary = {
            "status": status, "reason": reason, "plan_sha256": plan["plan_sha256"],
            "candidate_review_complete": False, "completed_method_questions": completed,
            "planned_method_questions": len(questions) * 3,
            "answer_status_counts": answer_status_counts,
            "unexpected_status_count": unexpected_status_count,
            "pilot_scored_against_references": False,
            "execution_checks_pass": (status == "COMPLETE" and not coverage["failed_ids"]
                                      and unexpected_status_count == 0),
            "actual_requests": guarded.requests, "recorded_transport_calls": recorder.calls,
            "input_tokens": guarded.input_tokens, "output_tokens": guarded.output_tokens,
            "estimated_cost_usd": (str(guarded.estimated_cost_usd)
                                   if guarded.estimated_cost_usd is not None else None),
            "extraction_coverage": coverage,
        }
        _durable_json(run_dir / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run check or one-shot DeepSeek dev pilot")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--manifest", default="data/processed/dev_pilot/manifest.json")
    parser.add_argument("--csv", default="data/processed/dev_pilot/pilot.csv")
    parser.add_argument("--questions", default="data/processed/dev_pilot/questions.json")
    parser.add_argument("--references", default="data/gold/dev_pilot/references.json")
    parser.add_argument("--split", default="data/processed/candidate_split.json")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-plan-sha256",
                        help="exact plan fingerprint separately approved for live execution")
    args = parser.parse_args(argv)
    try:
        plan = checked_plan(Path(args.plan), manifest_path=Path(args.manifest),
                            csv_path=Path(args.csv), questions_path=Path(args.questions),
                            references_path=Path(args.references), split_path=Path(args.split))
        if not args.execute:
            print(json.dumps({"mode": "DRY_RUN", "network_calls_made": 0,
                              "plan_sha256": plan["plan_sha256"],
                              "request_ceiling": plan["max_api_requests"]}))
            return 0
        if args.approved_plan_sha256 != plan["plan_sha256"]:
            raise ValueError("live execution requires the exact approved plan fingerprint")
        if not os.environ.get("DEEPSEEK_API_KEY"):
            raise ValueError("DEEPSEEK_API_KEY is unavailable")
        require_dev_run_balance(plan["max_cost_usd"])
        provider = ResponsesClient("deepseek", plan["model"],
                                   max_output_tokens=plan["max_output_tokens_per_request"],
                                   timeout_seconds=plan["timeout_seconds"], allow_network=True)
        summary = run_pilot(plan, csv_path=Path(args.csv),
                            questions_path=Path(args.questions), client=provider)
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary["execution_checks_pass"] else 3
    except (OSError, ValueError, KeyError, TypeError, BalanceError) as exc:
        print(f"pilot preflight failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
