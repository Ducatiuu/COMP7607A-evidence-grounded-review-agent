import pytest

from src.rate_semantics import rate_definition
from src.schemas import QuerySpec
from src.tools import AggregateArgs, FilterArgs, aggregate_aspects, filter_records
from test_tools import _dataset


def test_distinct_review_rate_basis_and_independent_subgroup():
    ctx = _dataset()
    query = QuerySpec(task_type="rate", categories=["service"], metric="negative_rate",
                      denominator_spec="aspect_mentions",
                      conditions=[{"category": "food", "sentiment": "positive"}])
    basis = rate_definition(query)
    assert basis["count_unit"] == "distinct_review_records"
    assert basis["rate_value_unit"] == "fraction"
    assert basis["scope_conditions"] == [{"category": "food", "sentiment": "positive"}]
    assert basis["numerator_definition"] == "scoped records labelled negative for each target category"
    assert basis["denominator_definition"] == "scoped records mentioning each target category with any sentiment"
    scope = filter_records(ctx, FilterArgs(conditions=query.conditions)).record_ids
    stat = aggregate_aspects(ctx, AggregateArgs(categories=["service"], metric="negative_rate",
                                                record_ids=scope)).stats[0]
    assert (scope, stat.numerator, stat.denominator, stat.rate) == (["R01", "R03"], 1, 2, 0.5)
    assert stat.negative_ids == ["R01"] and stat.mention_ids == ["R01", "R03"]


def test_zero_denominator_and_conflict_are_not_negative():
    ctx = _dataset()
    no_mentions = aggregate_aspects(ctx, AggregateArgs(categories=["ambience"], metric="negative_rate")).stats[0]
    assert (no_mentions.numerator, no_mentions.denominator, no_mentions.rate) == (0, 0, None)
    all_records_query = QuerySpec(task_type="rate", categories=["ambience"], metric="negative_rate",
                                  denominator_spec="all_records")
    assert rate_definition(all_records_query)["denominator_definition"] == "all scoped records"
    all_records = aggregate_aspects(ctx, AggregateArgs(categories=["ambience"], metric="negative_rate",
                                                       denominator_spec="all_records")).stats[0]
    assert (all_records.numerator, all_records.denominator, all_records.rate) == (0, 4, 0.0)
    changed = ctx.dataset.model_copy(deep=True)
    changed.extractions[1].aspects[0].sentiment = "conflict"
    from src.tools import AnalysisContext
    stat = aggregate_aspects(AnalysisContext(changed), AggregateArgs(categories=["service"],
                                                         metric="negative_rate")).stats[0]
    assert (stat.negative_count, stat.conflict_count, stat.denominator, stat.rate) == (1, 1, 3, pytest.approx(1 / 3))


def test_non_rate_has_no_rate_definition():
    assert rate_definition(QuerySpec(task_type="count", categories=["service"], metric="negative_count")) is None
