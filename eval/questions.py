"""Candidate question wording and independent gold-only reference calculation."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from src.schemas import Category
from src.schemas.models import StrictModel
from src.semeval import CandidateSplit, GoldRecord


class QuestionCandidate(StrictModel):
    question_id: str
    pack_id: str
    record_ids: list[str]
    task_type: Literal["count", "rate", "selection", "comparison", "evidence_explanation", "insufficient_info"]
    wording: str
    expected_fields: list[str]
    denominator_spec: Literal["aspect_mentions", "all_records"] | None = None
    status: Literal["CANDIDATE_UNREVIEWED"] = "CANDIDATE_UNREVIEWED"


class GoldReference(StrictModel):
    question_id: str
    task_type: str
    count: int | None = None
    numerator: int | None = None
    denominator: int | None = None
    rate: float | None = None
    selected_record_ids: list[str] = Field(default_factory=list)
    comparison_groups: list[list[Category]] = Field(default_factory=list)
    category_counts: dict[Category, int] = Field(default_factory=dict)
    source_record_ids: list[str] = Field(default_factory=list)
    insufficient_info: bool = False
    status: Literal["CANDIDATE_UNREVIEWED"] = "CANDIDATE_UNREVIEWED"


_TEMPLATES = [
    ("count", "How many reviews express negative sentiment about service?", ["count"], None),
    ("rate", "Among reviews mentioning service, what fraction express negative service sentiment?", ["numerator", "denominator", "rate"], "aspect_mentions"),
    ("selection", "Which reviews praise food and criticize service?", ["selected_record_ids"], None),
    ("comparison", "Which has more negative reviews, food or service? Include ties.", ["comparison_groups", "counts"], None),
    ("evidence_explanation", "Which of food, service, and price has the most negative reviews? Give source review IDs supporting the result.", ["comparison_groups", "counts", "source_record_ids"], None),
]

_MISSING_METADATA_TEMPLATES = [
    "How did negative service reviews change by month?",
    "What fraction of low-rated reviews criticize service?",
    "How many distinct customers complained about service?",
]


def build_candidate_questions(split: CandidateSplit) -> list[QuestionCandidate]:
    questions = []
    for pack_number, ids in enumerate(split.packs, start=1):
        pack_id = f"P{pack_number:02d}"
        templates = [*_TEMPLATES, ("insufficient_info", _MISSING_METADATA_TEMPLATES[(pack_number - 1) % 3],
                                  ["insufficient_info"], None)]
        for question_number, (task, wording, fields, denominator) in enumerate(templates, start=1):
            questions.append(QuestionCandidate(question_id=f"{pack_id}-Q{question_number}", pack_id=pack_id,
                                               record_ids=ids, task_type=task, wording=wording,
                                               expected_fields=fields, denominator_spec=denominator))
    return questions


def build_gold_references(questions: list[QuestionCandidate], gold: list[GoldRecord]) -> list[GoldReference]:
    by_id = {record.record_id: record for record in gold}
    if len(by_id) != len(gold):
        raise ValueError("duplicate gold record ID")
    references = []
    for question in questions:
        if len(question.record_ids) != len(set(question.record_ids)) or not set(question.record_ids).issubset(by_id):
            raise ValueError(f"missing or duplicate gold IDs for {question.question_id}")
        labels = {record_id: {aspect.category: aspect.sentiment for aspect in by_id[record_id].aspects} for record_id in question.record_ids}

        def negative_ids(category: Category) -> list[str]:
            return [record_id for record_id in question.record_ids if labels[record_id].get(category) == "negative"]

        service_negative = negative_ids(Category.SERVICE)
        if question.task_type == "count":
            reference = GoldReference(question_id=question.question_id, task_type=question.task_type, count=len(service_negative))
        elif question.task_type == "rate":
            mentions = [record_id for record_id in question.record_ids if Category.SERVICE in labels[record_id]]
            reference = GoldReference(question_id=question.question_id, task_type=question.task_type,
                                      numerator=len(service_negative), denominator=len(mentions),
                                      rate=len(service_negative) / len(mentions) if mentions else None)
        elif question.task_type == "selection":
            selected = [record_id for record_id in question.record_ids
                        if labels[record_id].get(Category.FOOD) == "positive" and labels[record_id].get(Category.SERVICE) == "negative"]
            reference = GoldReference(question_id=question.question_id, task_type=question.task_type, selected_record_ids=selected)
        elif question.task_type in {"comparison", "evidence_explanation"}:
            categories = [Category.FOOD, Category.SERVICE] if question.task_type == "comparison" else [Category.FOOD, Category.SERVICE, Category.PRICE]
            counts = {category: len(negative_ids(category)) for category in categories}
            groups = [[category for category in categories if counts[category] == value] for value in sorted(set(counts.values()), reverse=True)]
            winners = set(groups[0])
            source_ids = [record_id for record_id in question.record_ids if any(record_id in negative_ids(category) for category in winners)]
            reference = GoldReference(question_id=question.question_id, task_type=question.task_type,
                                      comparison_groups=groups, category_counts=counts, source_record_ids=source_ids)
        else:
            reference = GoldReference(question_id=question.question_id, task_type=question.task_type, insufficient_info=True)
        references.append(reference)
    return references
