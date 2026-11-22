"""Read-only, record-level ABSA analysis with explicit partial coverage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from src.schemas import AspectAnnotation, Category, Coverage, ExtractionDataset, Predicate, Sentiment
from src.schemas.models import StrictModel


@dataclass(frozen=True)
class AnalysisContext:
    dataset: ExtractionDataset

    def scope(self, record_ids: list[str] | None) -> list[str]:
        all_ids = [record.record_id for record in self.dataset.records]
        if record_ids is None:
            return all_ids
        if len(set(record_ids)) != len(record_ids) or not set(record_ids).issubset(all_ids):
            raise ValueError("scope contains duplicate or unknown record ID")
        selected = set(record_ids)
        return [record_id for record_id in all_ids if record_id in selected]

    def coverage(self, ids: list[str]) -> Coverage:
        by_id = {result.record_id: result for result in self.dataset.extractions}
        failed = [record_id for record_id in ids if by_id[record_id].status == "failed"]
        return Coverage(total=len(ids), success=len(ids) - len(failed), failed_ids=failed)


class FilterArgs(StrictModel):
    conditions: list[Predicate] = Field(min_length=1)
    operator: Literal["AND", "OR"] = "AND"
    record_ids: list[str] | None = None


class FilterResult(StrictModel):
    record_ids: list[str]
    count: int = Field(ge=0)
    scope_ids: list[str]
    status: Literal["ok", "partial"]
    coverage: Coverage


class AggregateArgs(StrictModel):
    categories: list[Category] = Field(default_factory=list)
    record_ids: list[str] | None = None
    metric: Literal["distinct_record_count", "mention_count", "negative_count", "negative_rate"] = "negative_count"
    denominator_spec: Literal["aspect_mentions", "all_records"] = "aspect_mentions"

    @model_validator(mode="after")
    def unique_categories(self) -> "AggregateArgs":
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("duplicate categories")
        if self.metric != "distinct_record_count" and not self.categories:
            raise ValueError("aspect metric requires categories")
        return self


class AspectStats(StrictModel):
    category: Category
    mention_count: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    negative_count: int = Field(ge=0)
    neutral_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    mention_ids: list[str]
    negative_ids: list[str]
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float | None


class AggregateResult(StrictModel):
    stats: list[AspectStats]
    metric: Literal["distinct_record_count", "mention_count", "negative_count", "negative_rate"]
    denominator_spec: Literal["aspect_mentions", "all_records"]
    scope_count: int = Field(ge=0)
    scope_ids: list[str]
    status: Literal["ok", "partial"]
    coverage: Coverage


class CompareArgs(StrictModel):
    categories: list[Category] = Field(min_length=2)
    metric: Literal["mention_count", "negative_count", "negative_rate"]
    denominator_spec: Literal["aspect_mentions", "all_records"] = "aspect_mentions"
    record_ids: list[str] | None = None

    @model_validator(mode="after")
    def unique_categories(self) -> "CompareArgs":
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("duplicate categories")
        return self


class CompareGroup(StrictModel):
    value: int | float
    categories: list[Category]


class CompareResult(StrictModel):
    metric: Literal["mention_count", "negative_count", "negative_rate"]
    denominator_spec: Literal["aspect_mentions", "all_records"]
    groups: list[CompareGroup]
    undefined_categories: list[Category]
    stats: list[AspectStats]
    scope_ids: list[str]
    status: Literal["ok", "partial"]
    coverage: Coverage


class EvidenceArgs(StrictModel):
    record_ids: list[str]
    categories: list[Category] = Field(default_factory=list)
    sentiments: list[Sentiment] = Field(default_factory=list)
    max_examples: int = Field(default=5, ge=1, le=100)


class EvidenceItem(StrictModel):
    record_id: str
    text: str
    aspects: list[AspectAnnotation]
    extraction_status: Literal["ok", "failed"]


class EvidenceResult(StrictModel):
    all_record_ids: list[str]
    examples: list[EvidenceItem]
    status: Literal["ok", "partial"]
    coverage: Coverage


def _context_maps(ctx: AnalysisContext):
    return {r.record_id: r for r in ctx.dataset.records}, {r.record_id: r for r in ctx.dataset.extractions}


def filter_records(ctx: AnalysisContext, args: FilterArgs) -> FilterResult:
    scope = ctx.scope(args.record_ids)
    _, results = _context_maps(ctx)
    matched: list[str] = []
    for record_id in scope:
        result = results[record_id]
        if result.status == "failed":
            continue
        pairs = {(a.category, a.sentiment) for a in result.aspects}
        categories = {a.category for a in result.aspects}
        matches = [
            (condition.category in categories if condition.sentiment is None else (condition.category, condition.sentiment) in pairs)
            for condition in args.conditions
        ]
        matched_conditions = all(matches) if args.operator == "AND" else any(matches)
        if matched_conditions:
            matched.append(record_id)
    coverage = ctx.coverage(scope)
    return FilterResult(record_ids=matched, count=len(matched), scope_ids=scope, status="partial" if coverage.failed_ids else "ok", coverage=coverage)


def _stats(ctx: AnalysisContext, scope: list[str], category: Category, denominator_spec: str, coverage: Coverage) -> AspectStats:
    _, results = _context_maps(ctx)
    by_sentiment: dict[Sentiment, list[str]] = {sentiment: [] for sentiment in Sentiment}
    mention_ids: list[str] = []
    for record_id in scope:
        result = results[record_id]
        if result.status == "failed":
            continue
        for aspect in result.aspects:
            if aspect.category == category:
                mention_ids.append(record_id)
                by_sentiment[aspect.sentiment].append(record_id)
    denominator = len(mention_ids) if denominator_spec == "aspect_mentions" else len(scope)
    numerator = len(by_sentiment[Sentiment.NEGATIVE])
    rate = None if denominator == 0 or (denominator_spec == "all_records" and coverage.failed_ids) else numerator / denominator
    return AspectStats(
        category=category, mention_count=len(mention_ids), positive_count=len(by_sentiment[Sentiment.POSITIVE]),
        negative_count=numerator, neutral_count=len(by_sentiment[Sentiment.NEUTRAL]),
        conflict_count=len(by_sentiment[Sentiment.CONFLICT]), mention_ids=mention_ids,
        negative_ids=by_sentiment[Sentiment.NEGATIVE], numerator=numerator,
        denominator=denominator, rate=rate,
    )


def aggregate_aspects(ctx: AnalysisContext, args: AggregateArgs) -> AggregateResult:
    scope = ctx.scope(args.record_ids)
    coverage = ctx.coverage(scope)
    return AggregateResult(
        stats=[_stats(ctx, scope, category, args.denominator_spec, coverage) for category in args.categories],
        metric=args.metric, denominator_spec=args.denominator_spec, scope_count=len(scope), scope_ids=scope,
        status="partial" if coverage.failed_ids else "ok", coverage=coverage,
    )


def compare_aspects(ctx: AnalysisContext, args: CompareArgs) -> CompareResult:
    scope = ctx.scope(args.record_ids)
    coverage = ctx.coverage(scope)
    stats = [_stats(ctx, scope, category, args.denominator_spec, coverage) for category in args.categories]
    values: dict[int | float, list[Category]] = {}
    undefined: list[Category] = []
    for stat in stats:
        value = stat.rate if args.metric == "negative_rate" else getattr(stat, args.metric)
        if value is None:
            undefined.append(stat.category)
        else:
            values.setdefault(value, []).append(stat.category)
    return CompareResult(
        metric=args.metric, denominator_spec=args.denominator_spec,
        groups=[CompareGroup(value=value, categories=values[value]) for value in sorted(values, reverse=True)],
        undefined_categories=undefined, stats=stats, scope_ids=scope,
        status="partial" if coverage.failed_ids else "ok", coverage=coverage,
    )


def get_evidence(ctx: AnalysisContext, args: EvidenceArgs) -> EvidenceResult:
    scope = ctx.scope(args.record_ids)
    records, results = _context_maps(ctx)
    examples: list[EvidenceItem] = []
    for record_id in scope[:args.max_examples]:
        result = results[record_id]
        aspects = [
            aspect for aspect in result.aspects
            if (not args.categories or aspect.category in args.categories)
            and (not args.sentiments or aspect.sentiment in args.sentiments)
        ]
        examples.append(EvidenceItem(record_id=record_id, text=records[record_id].text, aspects=aspects, extraction_status=result.status))
    coverage = ctx.coverage(scope)
    return EvidenceResult(all_record_ids=scope, examples=examples, status="partial" if coverage.failed_ids else "ok", coverage=coverage)
