"""Deterministic meaning of a negative aspect rate; never reads Gold labels."""

from __future__ import annotations

from src.schemas import QuerySpec


def rate_definition(query: QuerySpec) -> dict[str, object] | None:
    """Describe the population, two counts and units for a parsed rate query."""
    if query.task_type != "rate":
        return None
    return {
        "target_categories": [category.value for category in query.categories],
        "scope_conditions": [condition.model_dump(mode="json") for condition in query.conditions],
        "scope_operator": (query.operator or "AND") if query.conditions else None,
        "count_unit": "distinct_review_records",
        "numerator_definition": "scoped records labelled negative for each target category",
        "denominator_definition": (
            "scoped records mentioning each target category with any sentiment"
            if query.denominator_spec == "aspect_mentions" else
            "all scoped records"
        ),
        "denominator_spec": query.denominator_spec,
        "conflict_in_numerator": False,
        "conflict_in_denominator": True,
        "zero_denominator_value": None,
        "rate_value_unit": "fraction",
    }
