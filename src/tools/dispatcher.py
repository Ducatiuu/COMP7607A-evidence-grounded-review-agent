"""Allowlisted tool calls; model-supplied names and arguments are only data."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from src.schemas import ToolResult
from src.schemas.models import StrictModel
from .analysis import (
    AggregateArgs, AnalysisContext, CompareArgs, EvidenceArgs, FilterArgs,
    aggregate_aspects, compare_aspects, filter_records, get_evidence,
)


class ToolCall(StrictModel):
    name: Literal["filter_records", "aggregate_aspects", "compare_aspects", "get_evidence"]
    arguments: dict[str, Any] = Field(default_factory=dict)


_TOOLS = {
    "filter_records": (FilterArgs, filter_records),
    "aggregate_aspects": (AggregateArgs, aggregate_aspects),
    "compare_aspects": (CompareArgs, compare_aspects),
    "get_evidence": (EvidenceArgs, get_evidence),
}


def dispatch_tool(ctx: AnalysisContext, *, call_id: str, name: str, arguments: dict[str, Any]) -> ToolResult:
    if name not in _TOOLS:
        return ToolResult(call_id=call_id, tool_name=name, status="failed", error="unknown_tool", coverage=ctx.dataset.coverage)
    args_model, function = _TOOLS[name]
    try:
        args = args_model.model_validate(arguments)
        value = function(ctx, args)
        return ToolResult(
            call_id=call_id, tool_name=name, status=value.status,
            data=value.model_dump(mode="json"), coverage=value.coverage,
        )
    except (ValueError, TypeError):
        return ToolResult(call_id=call_id, tool_name=name, status="failed", error="invalid_tool_arguments_or_scope", coverage=ctx.dataset.coverage)
