"""Balance-gated, one-shot DeepSeek runs for user-loaded Streamlit records."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date
from pathlib import Path

from scripts.run_dev_pilot import CallRecorder
from src.absa_service import ExtractionService
from src.data_loader import dataset_fingerprint
from src.deepseek_balance import require_dev_run_balance
from src.live_cost import CostLimitedClient, plan_cost
from src.live_runtime import conservative_request_bound, run_model_method
from src.responses_client import ResponsesClient
from src.schemas import AnswerPayload, ExtractionDataset, RecordSet


PRICE_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing/"
MODEL = "deepseek-flash"
PRICE_DATE = "2026-11-24"
INPUT_RATE = "0.3"  # Official peak, cache-miss USD per million tokens.
OUTPUT_RATE = "1.2"  # Official peak USD per million tokens.
MAX_RECORDS = 30
MAX_INPUT_CHARS = 10_000
MAX_INPUT_TOKENS = 8192
MAX_OUTPUT_TOKENS = 2048


def _fresh_price() -> None:
    days = (date.today() - date.fromisoformat(PRICE_DATE)).days
    if days < 0 or days > 7:
        raise ValueError("DeepSeek price verification date is stale; update the checked rate configuration")


def _save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _begin(records: RecordSet, *, kind: str, request_limit: int, cap: str,
           root: Path, source_label: str,
           extra_manifest: dict[str, object] | None = None) -> tuple[Path, CostLimitedClient]:
    _fresh_price()
    if not 0 < len(records.records) <= MAX_RECORDS:
        raise ValueError("live UI supports 1 to 30 records per run")
    if sum(len(record.text) for record in records.records) > MAX_INPUT_CHARS:
        raise ValueError("review text exceeds live input character limit")
    plan = plan_cost(max_requests=request_limit,
                     max_input_tokens_per_request=MAX_INPUT_TOKENS,
                     max_output_tokens_per_request=MAX_OUTPUT_TOKENS,
                     max_cost_usd=cap, input_usd_per_million=INPUT_RATE,
                     output_usd_per_million=OUTPUT_RATE,
                     price_source=PRICE_SOURCE, price_date=PRICE_DATE)
    require_dev_run_balance(plan.max_cost_usd)
    root.mkdir(parents=True, exist_ok=True)
    directory = root / str(uuid.uuid4())
    directory.mkdir(exist_ok=False)
    _save(directory / "manifest.json", {
        "status": "IN_PROGRESS", "kind": kind, "data_scope": "USER_LOADED_CSV_OR_SYNTHETIC",
        "source_label": source_label, "record_count": len(records.records),
        "dataset_sha256": dataset_fingerprint(records), "model": MODEL,
        "request_limit": request_limit, "max_input_tokens": MAX_INPUT_TOKENS,
        "max_output_tokens": MAX_OUTPUT_TOKENS, "max_cost_usd": str(plan.max_cost_usd),
        "price_source": PRICE_SOURCE, "price_date": PRICE_DATE,
        **(extra_manifest or {}),
    })
    recorder = CallRecorder(ResponsesClient("deepseek", MODEL, max_output_tokens=MAX_OUTPUT_TOKENS,
                                            timeout_seconds=45, allow_network=True),
                            directory / "calls.jsonl")
    return directory, CostLimitedClient(recorder, plan)


def run_live_extraction(records: RecordSet, *, source_label: str,
                        root: Path = Path("outputs/ui_live_runs")) -> tuple[ExtractionDataset, dict]:
    request_limit = 2 * len(records.records)
    directory, guarded = _begin(records, kind="extraction", request_limit=request_limit,
                                cap="0.35", root=root, source_label=source_label,
                                extra_manifest={"extraction_prompt_version": "extract-v2"})
    try:
        result = ExtractionService(guarded, provider_model=MODEL, prompt_version="extract-v2").extract(records)
        _save(directory / "extraction.json", result.dataset.model_dump(mode="json"))
        summary = {"status": ("STOPPED" if guarded.frozen else
                              "PARTIAL" if result.dataset.coverage.failed_ids else "COMPLETE"),
                   "run_directory": str(directory), "requests": guarded.requests,
                   "input_tokens": guarded.input_tokens, "output_tokens": guarded.output_tokens,
                   "estimated_cost_usd": str(guarded.estimated_cost_usd) if guarded.estimated_cost_usd is not None else None,
                   "coverage": result.dataset.coverage.model_dump(mode="json")}
        _save(directory / "summary.json", summary)
        return result.dataset, summary
    except Exception as exc:
        _save(directory / "summary.json", {"status": "FAILED", "error_type": type(exc).__name__,
                                                "requests": guarded.requests})
        raise


def run_live_answer(records: RecordSet, *, question: str, method: str,
                    extraction: ExtractionDataset | None, source_label: str,
                    root: Path = Path("outputs/ui_live_runs")) -> tuple[AnswerPayload, dict]:
    if method not in {"a", "b", "c"} or not question.strip():
        raise ValueError("select a method and enter a question")
    if method in {"b", "c"} and extraction is None:
        raise ValueError("B/C requires a matching live extraction")
    if method == "a":
        extraction = None
    if sum(len(record.text) for record in records.records) + len(question) > MAX_INPUT_CHARS:
        raise ValueError("review text and question exceed live input character limit")
    bound = conservative_request_bound(method, len(records.records), prepared_extraction=extraction is not None)
    directory, guarded = _begin(records, kind=f"answer_{method}", request_limit=bound,
                                cap="0.05", root=root, source_label=source_label,
                                extra_manifest={
                                    "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
                                    "shared_extraction_sha256": (
                                        hashlib.sha256(extraction.model_dump_json().encode("utf-8")).hexdigest()
                                        if extraction is not None else None),
                                    "query_prompt_version": "query-v4", "answer_prompt_version": "answer-v6",
                                    "decision_prompt_version": "decision-v5", "direct_prompt_version": "direct-v3"})
    try:
        outcome = run_model_method(records, method=method, question=question,
                                   client=guarded, model_id=MODEL, max_api_requests=bound,
                                   max_records=MAX_RECORDS, max_input_chars=MAX_INPUT_CHARS,
                                   extraction_dataset=extraction,
                                   extraction_prompt_version="extract-v2",
                                   query_prompt_version="query-v4", answer_prompt_version="answer-v6",
                                   decision_prompt_version="decision-v5", direct_prompt_version="direct-v3")
        _save(directory / "answer.json", outcome.answer.model_dump(mode="json"))
        summary = {"status": "COMPLETE" if not guarded.frozen else "STOPPED",
                   "run_directory": str(directory), "requests": guarded.requests,
                   "input_tokens": guarded.input_tokens, "output_tokens": guarded.output_tokens,
                   "estimated_cost_usd": str(guarded.estimated_cost_usd) if guarded.estimated_cost_usd is not None else None,
                   "answer_status": outcome.answer.status,
                   "verification_scope": "schema_only" if method == "a" else "tool_and_source_consistency"}
        _save(directory / "summary.json", summary)
        return outcome.answer, summary
    except Exception as exc:
        _save(directory / "summary.json", {"status": "FAILED", "error_type": type(exc).__name__,
                                                "requests": guarded.requests})
        raise
