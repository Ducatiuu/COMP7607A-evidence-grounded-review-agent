"""Clearly synthetic fixtures for the one supported offline CLI demo question."""

from __future__ import annotations

from collections import deque

from src.data_loader import dataset_fingerprint
from src.llm_client import LLMResponse, MockLLMClient
from src.schemas import RecordSet


DEMO_QUESTION = "What is the negative service rate?"
DEMO_FINGERPRINT = "1bb30c2f4218d27770051a2cb22f10e64033a7c9c3320856210b154972424805"

_ASPECTS = {
    "R01": [("food", "positive", "food was great"), ("service", "negative", "service was slow")],
    "R02": [("service", "negative", "service was rude"), ("price", "negative", "price was too high")],
    "R03": [("service", "positive", "Friendly service"), ("food", "positive", "tasty food")],
    "R04": [("food", "neutral", "food was ordinary")],
}


def mock_for_demo(records: RecordSet, *, method: str, question: str | None = None) -> MockLLMClient:
    if dataset_fingerprint(records) != DEMO_FINGERPRINT:
        raise ValueError("MOCK CLI only supports the unchanged synthetic data/demo/core.csv")
    if question is not None and question != DEMO_QUESTION:
        raise ValueError(f"MOCK CLI only supports this exact question: {DEMO_QUESTION}")
    responses = []
    if method in {"extract", "b", "c"}:
        for record in records.records:
            responses.append(LLMResponse(content={
                "record_id": record.record_id,
                "aspects": [{"category": category, "sentiment": sentiment, "evidence": [quote]} for category, sentiment, quote in _ASPECTS[record.record_id]],
                "status": "ok", "error": None,
            }, model="mock"))
    if method in {"b", "c"}:
        responses.append(LLMResponse(content={
            "task_type": "rate", "categories": ["service"], "metric": "negative_rate",
            "denominator_spec": "aspect_mentions", "needs_evidence": False,
        }, model="mock"))
    if method == "b":
        responses.append(LLMResponse(content={
            "status": "ok", "answer_text": "Two of three service mentions are negative (66.7%).",
            "numeric_claims": [{"metric": "negative_rate", "category": "service", "scope_ids": ["R01", "R02", "R03", "R04"], "value": 2 / 3, "numerator": 2, "denominator": 3, "unit": "fraction"}],
            "denominator_explanation": "2 negative service records among 3 records mentioning service.",
        }, model="mock"))
    if method == "a":
        responses.append(LLMResponse(content={
            "status": "ok", "answer_text": "Two of three service mentions are negative (66.7%).",
            "numeric_claims": [{"metric": "negative_rate", "category": "service", "value": 2 / 3, "numerator": 2, "denominator": 3}],
            "denominator_explanation": "2 negative service records among 3 service mentions.",
        }, model="mock"))
    return MockLLMClient(deque(responses))
