"""Runtime structural checks against actual tool results, never gold labels."""

from __future__ import annotations

import math

from src.schemas import AnswerPayload, QuerySpec, ToolResult
from src.tools import AnalysisContext


def _same_value(expected, actual) -> bool:
    if expected is None or actual is None:
        return expected is actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(expected, actual, rel_tol=0, abs_tol=1e-9)
    return expected == actual


def _supported_claims(results: list[ToolResult]) -> list[dict]:
    supported: list[dict] = []
    for result in results:
        if result.status == "failed" or result.data is None:
            continue
        data = result.data
        if result.tool_name == "filter_records":
            supported.append({"metric": "distinct_record_count", "category": None, "scope_ids": data["record_ids"], "value": data["count"], "numerator": None, "denominator": None, "denominator_spec": None})
        if result.tool_name == "aggregate_aspects":
            supported.append({"metric": "distinct_record_count", "category": None, "scope_ids": data["scope_ids"], "value": data["scope_count"], "numerator": None, "denominator": None, "denominator_spec": None})
        if result.tool_name in {"aggregate_aspects", "compare_aspects"}:
            for stat in data["stats"]:
                for metric in ("mention_count", "positive_count", "negative_count", "neutral_count", "conflict_count", "negative_rate"):
                    is_rate = metric == "negative_rate"
                    supported.append({
                        "metric": metric, "category": stat["category"], "scope_ids": data["scope_ids"],
                        "value": stat["rate"] if is_rate else stat[metric],
                        "numerator": stat["numerator"] if is_rate else None,
                        "denominator": stat["denominator"] if is_rate else None,
                        "denominator_spec": data["denominator_spec"] if is_rate else None,
                    })
    return supported


def check_answer(answer: AnswerPayload, ctx: AnalysisContext, query: QuerySpec, results: list[ToolResult]) -> list[str]:
    errors: list[str] = []
    if answer.status == "ok" and any(result.status == "partial" for result in results):
        errors.append("tool_result_not_complete")
    if answer.status == "ok" and ctx.dataset.coverage.failed_ids:
        errors.append("extraction_coverage_partial")
    records = {record.record_id: record for record in ctx.dataset.records}
    evidence_ids = set()
    filter_ids: list[str] | None = None
    comparison_groups: list[list[str]] | None = None
    trace_by_call = {event.call_id: event for event in answer.tool_trace if event.call_id is not None}
    expected_scope = [record.record_id for record in ctx.dataset.records]
    for result in results:
        if result.status == "failed" or result.data is None:
            continue
        if result.tool_name == "get_evidence":
            evidence_ids.update(result.data["all_record_ids"])
        if result.tool_name == "filter_records" and query.conditions:
            event = trace_by_call.get(result.call_id)
            arguments = event.arguments if event is not None else None
            intended = [condition.model_dump(mode="json") for condition in query.conditions]
            if arguments and arguments.get("conditions") == intended and arguments.get("operator", "AND") == (query.operator or "AND") and arguments.get("record_ids") is None:
                filter_ids = result.data["record_ids"]
        if result.tool_name == "compare_aspects" and {stat["category"] for stat in result.data["stats"]} == {category.value for category in query.categories}:
            comparison_groups = [group["categories"] for group in result.data["groups"]]
    if query.conditions:
        if filter_ids is None:
            errors.append("missing_query_filter")
            expected_scope = None
        else:
            expected_scope = filter_ids
    for citation in answer.citations:
        record = records.get(citation.record_id)
        if record is None or citation.quote not in record.text:
            errors.append("invalid_citation_quote_or_id")
        elif citation.record_id not in evidence_ids:
            errors.append("citation_without_evidence_tool")
        elif expected_scope is not None and citation.record_id not in expected_scope:
            errors.append("citation_outside_query_scope")
    if len(set(answer.selected_record_ids)) != len(answer.selected_record_ids) or any(record_id not in records for record_id in answer.selected_record_ids):
        errors.append("invalid_selected_record_id")
    if query.task_type == "selection":
        if filter_ids is None or set(answer.selected_record_ids) != set(filter_ids):
            errors.append("selection_mismatch")
    if query.task_type == "comparison":
        actual_groups = [[category.value for category in group] for group in answer.comparison_groups]
        if comparison_groups is None or actual_groups != comparison_groups:
            errors.append("comparison_groups_mismatch")
    if query.task_type in {"count", "rate", "comparison"} and not answer.numeric_claims:
        errors.append("missing_numeric_claim")
    if query.task_type in {"count", "rate", "comparison"} and query.categories and query.metric and query.metric != "distinct_record_count":
        for category in query.categories:
            if not any(claim.category == category and claim.metric == query.metric for claim in answer.numeric_claims):
                errors.append("missing_target_claim")
    supported = _supported_claims(results)
    for claim in answer.numeric_claims:
        if expected_scope is not None and set(claim.scope_ids) != set(expected_scope):
            errors.append("numeric_claim_scope_mismatch")
        claim_category = claim.category.value if claim.category is not None else None
        matches = [item for item in supported if
            item["metric"] == claim.metric and item["category"] == claim_category
            and set(item["scope_ids"]) == set(claim.scope_ids)
            and _same_value(item["value"], claim.value)
            and item["numerator"] == claim.numerator
            and item["denominator"] == claim.denominator
            and (claim.metric != "negative_rate" or item["denominator_spec"] == query.denominator_spec)]
        if not matches:
            errors.append("unsupported_numeric_claim")
    if any(claim.metric == "negative_rate" for claim in answer.numeric_claims) and not answer.denominator_explanation:
        errors.append("missing_denominator_explanation")
    return sorted(set(errors))
