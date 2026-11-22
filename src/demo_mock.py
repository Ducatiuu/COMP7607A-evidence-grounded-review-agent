"""Clearly synthetic fixtures for the one supported offline CLI demo question."""

from __future__ import annotations

from collections import deque
import hashlib
import json
from pathlib import Path
from typing import Callable

from src.absa_service import ExtractionService
from src.controllers import DirectLLM, DynamicAgent, FixedWorkflow, QueryParser
from src.data_loader import dataset_fingerprint
from src.llm_client import LLMClient, LLMResponse, MockLLMClient
from src.schemas import AnswerPayload, ExtractionDataset, RecordSet
from src.tools import AnalysisContext
from src.verification import Finalizer


DEMO_QUESTION = "What is the negative service rate?"
DEMO_MISSING_DATE_QUESTION = "Did negative service reviews improve over the last month?"
DEMO_FINGERPRINT = "898bc06fac09734a7e65e2aadc33fc9af5684efeef445295c88f96c4cc021753"
PRESENTATION_FINGERPRINT = "0d1db0dd940beeb28bcaeea2fd8498131e91662806e63f54bd8875fce7abd5a9"
PRESENTATION_ANNOTATIONS_SHA256 = "a873b1b7817b74566d510617ff5d3602df16a878f08272fb53d5d2e9d2cfd43d"

_ASPECTS = {
    "R01": [("food", "positive", "food was great"), ("service", "negative", "service was slow")],
    "R02": [("food", "positive", "Delicious food"), ("price", "negative", "far too expensive")],
    "R03": [("service", "positive", "Friendly staff and quick service")],
    "R04": [("food", "negative", "Cold food"), ("service", "negative", "long wait")],
}


def _aspects_for_fixture(records: RecordSet) -> dict[str, list[tuple[str, str, str]]]:
    fingerprint = dataset_fingerprint(records)
    if fingerprint == DEMO_FINGERPRINT:
        return _ASPECTS
    if fingerprint != PRESENTATION_FINGERPRINT:
        raise ValueError("MOCK CLI supports only unchanged synthetic demo fixtures")
    path = Path(__file__).resolve().parents[1] / "data/demo/presentation_annotations.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != PRESENTATION_ANNOTATIONS_SHA256:
        raise ValueError("presentation annotations hash mismatch")
    entries = payload["records"]
    if payload.get("provenance") != "SIMULATED_MOCK_FIXTURE" or len(entries) != len(records.records):
        raise ValueError("presentation annotations are missing or misaligned")
    aspects = {}
    for record, entry in zip(records.records, entries):
        if entry["record_id"] != record.record_id or entry["text"] != record.text:
            raise ValueError("presentation annotations differ from raw records")
        aspects[record.record_id] = [(item["category"], item["sentiment"], item["evidence"][0])
                                     for item in entry["aspects"]]
    return aspects


def mock_for_demo(records: RecordSet, *, method: str, question: str | None = None, include_extraction: bool = True) -> MockLLMClient:
    fixture_aspects = _aspects_for_fixture(records)
    if question is not None and question not in {DEMO_QUESTION, DEMO_MISSING_DATE_QUESTION}:
        raise ValueError("MOCK CLI supports only the two displayed synthetic demo questions")
    responses = []
    service_mentions = [record.record_id for record in records.records
                        if any(category == "service" for category, _, _ in fixture_aspects[record.record_id])]
    service_negative = [record.record_id for record in records.records
                        if any(category == "service" and sentiment == "negative"
                               for category, sentiment, _ in fixture_aspects[record.record_id])]
    numerator, denominator = len(service_negative), len(service_mentions)
    rate = numerator / denominator if denominator else None
    if method == "extract" or (method in {"b", "c"} and include_extraction):
        for record in records.records:
            responses.append(LLMResponse(content={
                "record_id": record.record_id,
                "aspects": [{"category": category, "sentiment": sentiment, "evidence": [quote]} for category, sentiment, quote in fixture_aspects[record.record_id]],
                "status": "ok", "error": None,
            }, model="mock"))
    if question == DEMO_MISSING_DATE_QUESTION:
        if method == "a":
            responses.append(LLMResponse(content={"status": "insufficient_info", "answer_text": "No dates are available for these records."}, model="mock"))
        elif method in {"b", "c"}:
            responses.append(LLMResponse(content={"task_type": "insufficient_info", "metadata_required": ["date"]}, model="mock"))
        return MockLLMClient(deque(responses))
    if method in {"b", "c"}:
        responses.append(LLMResponse(content={
            "task_type": "rate", "categories": ["service"], "metric": "negative_rate",
            "denominator_spec": "aspect_mentions", "needs_evidence": False,
        }, model="mock"))
    if method == "c":
        responses.append(LLMResponse(content={"action": "call_tools", "calls": [{"name": "aggregate_aspects", "arguments": {"categories": ["service"], "metric": "negative_rate", "denominator_spec": "aspect_mentions"}}]}, model="mock"))
        responses.append(LLMResponse(content={"action": "finish", "calls": []}, model="mock"))
    if method in {"b", "c"}:
        responses.append(LLMResponse(content={
            "status": "ok", "answer_text": f"{numerator} of {denominator} service mentions are negative ({rate:.1%}).",
            "numeric_claims": [{"metric": "negative_rate", "category": "service", "scope_ids": [record.record_id for record in records.records],
                                "value": rate, "numerator": numerator, "denominator": denominator, "unit": "fraction"}],
            "denominator_explanation": f"{numerator} negative service records among {denominator} records mentioning service.",
        }, model="mock"))
    if method == "a":
        responses.append(LLMResponse(content={
            "status": "ok", "answer_text": f"{numerator} of {denominator} service mentions are negative ({rate:.1%}).",
            "numeric_claims": [{"metric": "negative_rate", "category": "service", "value": rate,
                                "numerator": numerator, "denominator": denominator}],
            "denominator_explanation": f"{numerator} negative service records among {denominator} service mentions.",
        }, model="mock"))
    return MockLLMClient(deque(responses))


def run_demo_method(records: RecordSet, *, method: str, question: str, question_id: str | None = None,
                    extraction_dataset: ExtractionDataset | None = None,
                    verify_outputs: bool = True,
                    client_wrapper: Callable[[LLMClient], LLMClient] | None = None) -> tuple[AnswerPayload, int]:
    """Execute a genuine local control path with synthetic model responses."""
    client = mock_for_demo(records, method=method, question=question, include_extraction=extraction_dataset is None)
    if client_wrapper is not None:
        client = client_wrapper(client)
    if question_id is None:
        question_id = "demo-date" if question == DEMO_MISSING_DATE_QUESTION else "demo-rate"
    if method == "a":
        return DirectLLM(client, "mock").run(records=records, question=question, question_id=question_id), 0
    if extraction_dataset is None:
        extraction = ExtractionService(client, provider_model="mock").extract(records)
        dataset = extraction.dataset
        extraction_requests = extraction.requests
    else:
        if extraction_dataset.records != records.records or extraction_dataset.fingerprint != dataset_fingerprint(records):
            raise ValueError("supplied extraction does not match demo records")
        dataset = extraction_dataset
        extraction_requests = 0
    ctx = AnalysisContext(dataset)
    if method == "b":
        answer = FixedWorkflow(QueryParser(client, "mock"), Finalizer(client, "mock", verify_outputs=verify_outputs)).run(ctx=ctx, question=question, question_id=question_id)
    elif method == "c":
        answer = DynamicAgent(QueryParser(client, "mock"), client, Finalizer(client, "mock", verify_outputs=verify_outputs), "mock").run(ctx=ctx, question=question, question_id=question_id)
    else:
        raise ValueError("unsupported demo method")
    usage = {**answer.usage, "extraction_requests": extraction_requests,
             "api_requests": (answer.usage.get("api_requests") or 0) + extraction_requests}
    return answer.model_copy(update={"usage": usage}), extraction_requests
