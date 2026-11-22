"""Boundary models. Unknown input fields are rejected rather than trusted."""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Category(str, Enum):
    FOOD = "food"
    SERVICE = "service"
    PRICE = "price"
    AMBIENCE = "ambience"
    ANECDOTES_MISCELLANEOUS = "anecdotes/miscellaneous"


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    CONFLICT = "conflict"


class Record(StrictModel):
    record_id: str
    text: str

    @model_validator(mode="before")
    @classmethod
    def generate_missing_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("record_id") and isinstance(data.get("text"), str):
            data = {**data, "record_id": "auto-" + hashlib.sha256(data["text"].encode("utf-8")).hexdigest()[:16]}
        return data

    @field_validator("record_id", "text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("record ID and text must be nonblank")
        return value


class RecordSet(StrictModel):
    records: list[Record]

    @model_validator(mode="after")
    def unique_ids(self) -> "RecordSet":
        ids = [r.record_id for r in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate record_id")
        return self


class AspectAnnotation(StrictModel):
    category: Category
    sentiment: Sentiment
    evidence: list[str] = Field(min_length=1)

    @field_validator("evidence")
    @classmethod
    def spans_nonblank(cls, spans: list[str]) -> list[str]:
        if any(not span.strip() for span in spans):
            raise ValueError("evidence spans must be nonblank")
        return spans


class ExtractionResult(StrictModel):
    record_id: str = Field(min_length=1)
    aspects: list[AspectAnnotation]
    status: Literal["ok", "failed"]
    error: str | None = None

    @field_validator("record_id")
    @classmethod
    def nonblank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("record_id must be nonblank")
        return value

    @model_validator(mode="after")
    def status_and_categories(self) -> "ExtractionResult":
        categories = [aspect.category for aspect in self.aspects]
        if len(categories) != len(set(categories)):
            raise ValueError("duplicate category in one record")
        if self.status == "failed" and (self.aspects or not self.error or not self.error.strip()):
            raise ValueError("failed extraction needs an error and no aspects")
        if self.status == "ok" and self.error is not None:
            raise ValueError("successful extraction cannot contain an error")
        return self

    def validate_evidence(self, record: Record) -> None:
        if self.record_id != record.record_id:
            raise ValueError("extraction record_id mismatch")
        for aspect in self.aspects:
            for span in aspect.evidence:
                if span not in record.text:
                    raise ValueError(f"evidence is not an exact source substring: {span!r}")


class Coverage(StrictModel):
    total: int = Field(ge=0)
    success: int = Field(ge=0)
    failed_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def counts_consistent(self) -> "Coverage":
        if self.success + len(self.failed_ids) != self.total or len(set(self.failed_ids)) != len(self.failed_ids):
            raise ValueError("coverage counts or failed IDs are inconsistent")
        return self


class ExtractionDataset(StrictModel):
    fingerprint: str = Field(min_length=1)
    records: list[Record]
    extractions: list[ExtractionResult]
    provider_model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    evidence_origin: Literal["model_span", "full_sentence_unannotated"] = "model_span"
    coverage: Coverage

    @model_validator(mode="after")
    def aligned(self) -> "ExtractionDataset":
        RecordSet(records=self.records)
        record_by_id = {r.record_id: r for r in self.records}
        result_ids = [r.record_id for r in self.extractions]
        if len(result_ids) != len(set(result_ids)) or set(result_ids) != set(record_by_id):
            raise ValueError("extraction IDs must match record IDs exactly")
        for result in self.extractions:
            result.validate_evidence(record_by_id[result.record_id])
        failed_ids = [r.record_id for r in self.extractions if r.status == "failed"]
        if self.coverage.total != len(self.records) or self.coverage.success != len(self.records) - len(failed_ids) or self.coverage.failed_ids != failed_ids:
            raise ValueError("coverage does not match extraction results")
        return self


class Predicate(StrictModel):
    category: Category
    sentiment: Sentiment | None = None


class QuerySpec(StrictModel):
    task_type: Literal["count", "rate", "selection", "comparison", "evidence_explanation", "insufficient_info", "clarification", "unsupported"]
    operator: Literal["AND", "OR"] | None = None
    conditions: list[Predicate] = Field(default_factory=list)
    categories: list[Category] = Field(default_factory=list)
    metric: Literal["distinct_record_count", "mention_count", "negative_count", "negative_rate"] | None = None
    denominator_spec: Literal["aspect_mentions", "all_records"] | None = None
    metadata_required: list[Literal["date", "rating", "customer_id"]] = Field(default_factory=list)
    needs_evidence: bool = False
    ambiguity_note: str | None = None

    @model_validator(mode="after")
    def coherent(self) -> "QuerySpec":
        if len(self.conditions) > 1 and self.operator is None:
            raise ValueError("multiple conditions require AND or OR")
        if self.operator is not None and not self.conditions:
            raise ValueError("operator without conditions")
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("duplicate target categories")
        if self.task_type == "rate" and self.denominator_spec is None:
            raise ValueError("rate requires an explicit denominator")
        if self.task_type == "rate" and (not self.categories or self.metric != "negative_rate"):
            raise ValueError("rate requires target categories and negative_rate metric")
        if self.task_type == "selection" and not self.conditions:
            raise ValueError("selection requires conditions")
        if self.task_type == "comparison" and (len(self.categories) < 2 or self.metric is None):
            raise ValueError("comparison requires at least two categories and a metric")
        if self.task_type != "rate" and self.denominator_spec is not None and self.metric != "negative_rate":
            raise ValueError("denominator supplied for a non-rate metric")
        return self


class NumericClaim(StrictModel):
    metric: str = Field(min_length=1)
    category: Category | None = None
    scope_ids: list[str] = Field(default_factory=list)
    value: float | int | None = None
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=0)
    unit: str | None = None


class Citation(StrictModel):
    record_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    category: Category | None = None
    sentiment: Sentiment | None = None


class TraceEvent(StrictModel):
    run_id: str = Field(min_length=1)
    question_id: str | None = None
    method: Literal["a", "b", "c"]
    stage: str = Field(min_length=1)
    decision_round: int | None = Field(default=None, ge=1)
    call_id: str | None = None
    status: Literal["ok", "failed", "invalid"]
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    result_summary: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)


class ToolResult(StrictModel):
    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    status: Literal["ok", "partial", "failed"]
    data: dict[str, Any] | None = None
    error: str | None = None
    coverage: Coverage


class AnswerPayload(StrictModel):
    method: Literal["a", "b", "c"]
    question_id: str | None = None
    status: Literal["ok", "partial", "insufficient_info", "clarification", "failed"]
    answer_text: str
    numeric_claims: list[NumericClaim] = Field(default_factory=list)
    selected_record_ids: list[str] = Field(default_factory=list)
    comparison_groups: list[list[Category]] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    denominator_explanation: str | None = None
    coverage: Coverage | None = None
    tool_trace: list[TraceEvent] = Field(default_factory=list)
    error_code: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def failed_has_error(self) -> "AnswerPayload":
        if self.status == "failed" and not self.error_code:
            raise ValueError("failed answer needs an error_code")
        if len(self.selected_record_ids) != len(set(self.selected_record_ids)):
            raise ValueError("duplicate selected record ID")
        return self
