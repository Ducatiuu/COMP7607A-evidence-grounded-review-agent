"""Gold-only offline scoring. Runtime methods must never import this module."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from typing import Literal

from pydantic import Field, model_validator

from src.schemas import AnswerPayload, Category, ExtractionDataset, Record, Sentiment
from src.schemas.models import StrictModel
from src.semeval import GoldRecord
from .questions import GoldReference


@dataclass(frozen=True)
class F1Counts:
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        denominator = 2 * self.tp + self.fp + self.fn
        return 2 * self.tp / denominator if denominator else 1.0


def set_f1(predicted: set, gold: set) -> F1Counts:
    return F1Counts(tp=len(predicted & gold), fp=len(predicted - gold), fn=len(gold - predicted))


def absa_scores(dataset: ExtractionDataset, gold: list[GoldRecord]) -> dict:
    gold_by_id = {record.record_id: record for record in gold}
    if len(gold_by_id) != len(gold) or set(gold_by_id) != {record.record_id for record in dataset.records}:
        raise ValueError("gold and prediction record IDs must align exactly")
    predicted_categories = set()
    gold_categories = set()
    predicted_joint = set()
    gold_joint = set()
    for result in dataset.extractions:
        if result.status == "ok":
            for aspect in result.aspects:
                predicted_categories.add((result.record_id, aspect.category))
                predicted_joint.add((result.record_id, aspect.category, aspect.sentiment))
    for record in gold:
        for aspect in record.aspects:
            key = (record.record_id, aspect.category)
            gold_categories.add(key)
            gold_joint.add((record.record_id, aspect.category, aspect.sentiment))
    return {
        "category_micro": set_f1(predicted_categories, gold_categories).__dict__,
        "category_micro_f1": set_f1(predicted_categories, gold_categories).f1,
        "joint_micro": set_f1(predicted_joint, gold_joint).__dict__,
        "joint_micro_f1": set_f1(predicted_joint, gold_joint).f1,
        "extraction_failed_ids": dataset.coverage.failed_ids,
        "extraction_success_rate": dataset.coverage.success / dataset.coverage.total if dataset.coverage.total else None,
    }


class ConditionedPrediction(StrictModel):
    record_id: str = Field(min_length=1)
    category: Category
    sentiment: Sentiment | None = None
    status: Literal["ok", "failed"] = "ok"

    @model_validator(mode="after")
    def status_consistency(self) -> "ConditionedPrediction":
        if (self.status == "ok") != (self.sentiment is not None):
            raise ValueError("conditioned status and sentiment disagree")
        return self


def conditioned_sentiment_scores(predictions: list[ConditionedPrediction], gold: list[GoldRecord]) -> dict:
    """Score a separate gold-category-conditioned prompt, never joint extraction."""
    gold_map = {(record.record_id, aspect.category): aspect.sentiment for record in gold for aspect in record.aspects}
    prediction_map = {}
    for prediction in predictions:
        key = (prediction.record_id, prediction.category)
        if key not in gold_map or key in prediction_map:
            raise ValueError("conditioned predictions must align one-to-one with gold categories")
        prediction_map[key] = prediction.sentiment if prediction.status == "ok" else None
    by_class = {}
    macro_values = []
    for sentiment in Sentiment:
        expected = {key for key, label in gold_map.items() if label == sentiment}
        predicted = {key for key, label in prediction_map.items() if label == sentiment}
        counts = set_f1(predicted, expected)
        support = len(expected)
        by_class[sentiment.value] = {**counts.__dict__, "support": support, "f1": counts.f1 if support or predicted else None}
        if support or predicted:
            macro_values.append(counts.f1)
    return {"macro_f1": sum(macro_values) / len(macro_values) if macro_values else None,
            "by_sentiment": by_class, "expected_pairs": len(gold_map), "received_pairs": len(prediction_map)}


def _matching_claim(answer: AnswerPayload, metric: str, category: str | None):
    return next((claim for claim in answer.numeric_claims if claim.metric == metric and (claim.category.value if claim.category else None) == category), None)


def _counts_correct(answer: AnswerPayload, reference: GoldReference) -> bool:
    return all((claim := _matching_claim(answer, "negative_count", category.value)) is not None and claim.value == count
               for category, count in reference.category_counts.items())


def score_answer(answer: AnswerPayload, reference: GoldReference, records: list[Record] | None = None) -> dict:
    if answer.question_id != reference.question_id:
        raise ValueError("question ID mismatch")
    complete = answer.status == "ok"
    false_refusal = answer.status == "insufficient_info" and reference.task_type != "insufficient_info"
    result = {"question_id": reference.question_id, "task_type": reference.task_type,
              "answer_status": answer.status, "primary_success": False, "false_refusal": false_refusal,
              "selection_f1": None, "selection_exact": None, "rate_undefined": False}
    if reference.task_type == "insufficient_info":
        result["primary_success"] = answer.status == "insufficient_info"
        return result
    if reference.task_type == "selection":
        predicted = set(answer.selected_record_ids)
        gold = set(reference.selected_record_ids)
        scores = set_f1(predicted, gold)
        result["selection_f1"] = scores.f1
        result["selection_exact"] = predicted == gold
        result["primary_success"] = complete and predicted == gold
        return result
    if reference.task_type == "count":
        claim = _matching_claim(answer, "negative_count", "service")
        result["primary_success"] = complete and claim is not None and claim.value == reference.count
        return result
    if reference.task_type == "rate":
        claim = _matching_claim(answer, "negative_rate", "service")
        result["rate_undefined"] = reference.rate is None
        if claim is None:
            return result
        value_ok = claim.value is None if reference.rate is None else claim.value is not None and abs(claim.value - reference.rate) <= 0.001
        result["primary_success"] = complete and value_ok and claim.numerator == reference.numerator and claim.denominator == reference.denominator and bool(answer.denominator_explanation)
        return result
    if reference.task_type in {"comparison", "evidence_explanation"}:
        groups_ok = answer.comparison_groups == reference.comparison_groups
        counts_ok = _counts_correct(answer, reference)
        evidence_ok = True
        if reference.task_type == "evidence_explanation":
            record_by_id = {record.record_id: record for record in records or []}
            evidence_ok = (not reference.source_record_ids and not answer.citations) or (
                bool(answer.citations) and all(citation.record_id in reference.source_record_ids
                                               and citation.record_id in record_by_id
                                               and citation.quote in record_by_id[citation.record_id].text
                                               for citation in answer.citations)
            )
        result["primary_success"] = complete and groups_ok and counts_ok and evidence_ok
        return result
    raise ValueError("unsupported reference task type")


def summarize_question_scores(scores: list[dict]) -> dict:
    by_type: dict[str, list[bool]] = defaultdict(list)
    for score in scores:
        by_type[score["task_type"]].append(bool(score["primary_success"]))
    per_type = {task: sum(values) / len(values) for task, values in by_type.items()}
    return {"question_count": len(scores), "per_type_success": per_type,
            "equal_type_average": sum(per_type.values()) / len(per_type) if per_type else None,
            "false_refusals": sum(bool(score["false_refusal"]) for score in scores)}
