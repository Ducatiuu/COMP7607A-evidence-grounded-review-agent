import pytest
from pydantic import ValidationError

from src.schemas import Coverage, ExtractionDataset, ExtractionResult, Record
from src.tools import (
    AggregateArgs, AnalysisContext, CompareArgs, EvidenceArgs, FilterArgs,
    aggregate_aspects, compare_aspects, filter_records, get_evidence,
)


def _dataset(failed_last=False):
    entries = [
        ("R01", "The food was great, but the service was slow.", [("food", "positive", "food was great"), ("service", "negative", "service was slow")]),
        ("R02", "The service was rude and the price was too high.", [("service", "negative", "service was rude"), ("price", "negative", "price was too high")]),
        ("R03", "Friendly service and tasty food.", [("service", "positive", "Friendly service"), ("food", "positive", "tasty food")]),
        ("R04", "The food was ordinary.", [("food", "neutral", "food was ordinary")]),
    ]
    records = [Record(record_id=record_id, text=text) for record_id, text, _ in entries]
    results = []
    for record_id, _, aspects in entries:
        if failed_last and record_id == "R04":
            results.append(ExtractionResult(record_id=record_id, aspects=[], status="failed", error="fixture failure"))
        else:
            results.append(ExtractionResult(record_id=record_id, aspects=[{"category": c, "sentiment": s, "evidence": [quote]} for c, s, quote in aspects], status="ok"))
    return AnalysisContext(ExtractionDataset(
        fingerprint="synthetic-core", records=records, extractions=results,
        provider_model="fixture", prompt_version="v1", schema_version="v1",
        coverage=Coverage(total=4, success=3 if failed_last else 4, failed_ids=["R04"] if failed_last else []),
    ))


def test_filter_and_or_use_record_set_not_row_cartesian_product():
    ctx = _dataset()
    conditions = [{"category": "food", "sentiment": "positive"}, {"category": "service", "sentiment": "negative"}]
    both = filter_records(ctx, FilterArgs(conditions=conditions, operator="AND"))
    either = filter_records(ctx, FilterArgs(conditions=conditions, operator="OR"))
    assert (both.record_ids, both.count) == (["R01"], 1)
    assert either.record_ids == ["R01", "R02", "R03"]
    with pytest.raises(ValueError, match="unknown record"):
        filter_records(ctx, FilterArgs(conditions=conditions, record_ids=["unknown"]))


def test_hand_calculated_counts_rates_and_undefined():
    ctx = _dataset()
    result = aggregate_aspects(ctx, AggregateArgs(categories=["service", "price", "ambience"], metric="negative_rate"))
    service, price, ambience = result.stats
    assert (service.mention_count, service.negative_count, service.positive_count, service.rate) == (3, 2, 1, 2 / 3)
    assert (price.mention_count, price.negative_count, price.rate) == (1, 1, 1)
    assert (ambience.mention_count, ambience.negative_count, ambience.rate) == (0, 0, None)
    all_records = aggregate_aspects(ctx, AggregateArgs(categories=["service"], metric="negative_rate", denominator_spec="all_records"))
    assert (all_records.stats[0].numerator, all_records.stats[0].denominator, all_records.stats[0].rate) == (2, 4, 0.5)
    assert aggregate_aspects(ctx, AggregateArgs(metric="distinct_record_count")).scope_count == 4


def test_conflict_is_not_negative_and_scope_is_distinct_records():
    ctx = _dataset()
    changed = ctx.dataset.model_copy(deep=True)
    changed.extractions[2].aspects[0].sentiment = "conflict"
    result = aggregate_aspects(AnalysisContext(changed), AggregateArgs(categories=["service"]))
    assert (result.stats[0].negative_count, result.stats[0].conflict_count) == (2, 1)
    assert result.stats[0].negative_ids == ["R01", "R02"]


def test_comparison_preserves_ties_and_undefined():
    ctx = _dataset()
    result = compare_aspects(ctx, CompareArgs(categories=["service", "price", "ambience"], metric="negative_count"))
    assert [(g.value, [c.value for c in g.categories]) for g in result.groups] == [(2, ["service"]), (1, ["price"]), (0, ["ambience"])]
    ties = compare_aspects(ctx, CompareArgs(categories=["service", "food"], metric="mention_count"))
    assert len(ties.groups) == 1
    assert [c.value for c in ties.groups[0].categories] == ["service", "food"]
    rates = compare_aspects(ctx, CompareArgs(categories=["price", "ambience"], metric="negative_rate"))
    assert [c.value for c in rates.undefined_categories] == ["ambience"]


def test_partial_extraction_is_not_full_population_rate():
    ctx = _dataset(failed_last=True)
    filtered = filter_records(ctx, FilterArgs(conditions=[{"category": "food"}]))
    assert filtered.status == "partial" and filtered.coverage.failed_ids == ["R04"]
    observed = aggregate_aspects(ctx, AggregateArgs(categories=["service"], metric="negative_rate"))
    assert observed.status == "partial" and observed.stats[0].rate == 2 / 3
    population = aggregate_aspects(ctx, AggregateArgs(categories=["service"], metric="negative_rate", denominator_spec="all_records"))
    assert population.status == "partial" and population.stats[0].rate is None


def test_evidence_has_exact_source_and_limited_examples_but_all_ids():
    ctx = _dataset()
    result = get_evidence(ctx, EvidenceArgs(record_ids=["R03", "R01", "R02"], categories=["service"], sentiments=["negative"], max_examples=1))
    assert result.all_record_ids == ["R01", "R02", "R03"]
    assert len(result.examples) == 1
    assert result.examples[0].text == "The food was great, but the service was slow."
    assert result.examples[0].aspects[0].evidence == ["service was slow"]
    empty = get_evidence(ctx, EvidenceArgs(record_ids=[]))
    assert empty.all_record_ids == [] and empty.examples == [] and empty.coverage.total == 0
    with pytest.raises(ValueError, match="unknown record"):
        get_evidence(ctx, EvidenceArgs(record_ids=["missing"]))


def test_tool_args_reject_invalid_category_and_duplicates():
    with pytest.raises(ValidationError):
        AggregateArgs(categories=["food", "food"])
    with pytest.raises(ValidationError):
        CompareArgs(categories=["food", "bad"], metric="negative_count")
