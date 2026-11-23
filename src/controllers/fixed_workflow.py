"""Method B: deterministic recipe chosen from the shared QuerySpec."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from src.schemas import AnswerPayload, QuerySpec, ToolResult, TraceEvent
from src.tools import AnalysisContext, dispatch_tool, trace_summary
from src.verification import Finalizer
from .query_parser import ParseOutcome, QueryParser


@dataclass
class FixedWorkflow:
    parser: QueryParser
    finalizer: Finalizer

    def run(self, *, ctx: AnalysisContext, question: str, question_id: str | None = None,
            parsed: ParseOutcome | None = None) -> AnswerPayload:
        outcome = parsed if parsed is not None else self.parser.parse(question)
        if outcome.status != "ok" or outcome.query is None:
            return _parse_failure("b", question_id, outcome, ctx)
        query = outcome.query
        if query.task_type in {"insufficient_info", "clarification", "unsupported"}:
            status = "insufficient_info" if query.task_type == "insufficient_info" else "clarification" if query.task_type == "clarification" else "failed"
            return AnswerPayload(method="b", question_id=question_id, status=status,
                                 answer_text="Required information is unavailable." if status == "insufficient_info" else "",
                                 error_code="unsupported_query" if status == "failed" else None,
                                 coverage=ctx.dataset.coverage, usage={"parser_requests": outcome.requests, "api_requests": outcome.requests})
        run_id = str(uuid.uuid4())
        trace: list[TraceEvent] = []
        results: list[ToolResult] = []

        def call(name: str, arguments: dict[str, Any]) -> ToolResult:
            start = time.perf_counter()
            call_id = f"{run_id}-{len(results) + 1}"
            result = dispatch_tool(ctx, call_id=call_id, name=name, arguments=arguments)
            results.append(result)
            trace.append(TraceEvent(
                run_id=run_id, question_id=question_id, method="b", stage="analysis_tool",
                call_id=call_id, status="ok" if result.status != "failed" else "failed", tool_name=name,
                arguments=arguments, result_summary=trace_summary(result), error=result.error,
                latency_ms=(time.perf_counter() - start) * 1000,
            ))
            return result

        scope_ids: list[str] | None = None
        if query.conditions:
            filtered = call("filter_records", {"conditions": [condition.model_dump(mode="json") for condition in query.conditions], "operator": query.operator or "AND"})
            if filtered.status == "failed":
                return _tool_failure("b", question_id, ctx, trace, outcome)
            scope_ids = filtered.data["record_ids"]

        if query.task_type in {"count", "rate"}:
            if query.metric == "distinct_record_count" and query.conditions:
                pass  # filter result already supplies the distinct record count
            else:
                result = call("aggregate_aspects", {"categories": [c.value for c in query.categories], "record_ids": scope_ids,
                                                    "metric": query.metric or "negative_count", "denominator_spec": query.denominator_spec or "aspect_mentions"})
                if result.status == "failed":
                    return _tool_failure("b", question_id, ctx, trace, outcome)
        elif query.task_type == "selection":
            if not query.conditions:
                return _tool_failure("b", question_id, ctx, trace, outcome)
        elif query.task_type == "comparison":
            result = call("compare_aspects", {"categories": [c.value for c in query.categories], "metric": query.metric,
                                               "denominator_spec": query.denominator_spec or "aspect_mentions", "record_ids": scope_ids})
            if result.status == "failed":
                return _tool_failure("b", question_id, ctx, trace, outcome)
        elif query.task_type == "evidence_explanation":
            if query.categories:
                result = call("aggregate_aspects", {"categories": [c.value for c in query.categories], "record_ids": scope_ids,
                                                    "metric": query.metric or "negative_count"})
                if result.status == "failed":
                    return _tool_failure("b", question_id, ctx, trace, outcome)
        else:
            return _tool_failure("b", question_id, ctx, trace, outcome)

        if query.needs_evidence or query.task_type == "evidence_explanation":
            evidence_ids = _evidence_ids(ctx, results, scope_ids, query.metric)
            result = call("get_evidence", {"record_ids": evidence_ids, "categories": [c.value for c in query.categories]})
            if result.status == "failed":
                return _tool_failure("b", question_id, ctx, trace, outcome)

        answer = self.finalizer.finish(method="b", question=question, question_id=question_id,
                                       query=query, ctx=ctx, results=results, trace=trace)
        usage = {**answer.usage, "parser_requests": outcome.requests,
                 "api_requests": (answer.usage.get("api_requests") or 0) + outcome.requests,
                 "input_tokens": _sum_known(answer.usage.get("input_tokens"), outcome.input_tokens),
                 "output_tokens": _sum_known(answer.usage.get("output_tokens"), outcome.output_tokens),
                 "analysis_tool_calls": len(results)}
        return answer.model_copy(update={"usage": usage})


def _sum_known(first: int | None, second: int | None) -> int | None:
    return first + second if first is not None and second is not None else None


def _evidence_ids(ctx: AnalysisContext, results: list[ToolResult], scope_ids: list[str] | None, metric: str | None) -> list[str]:
    if scope_ids is not None:
        return scope_ids
    for result in reversed(results):
        if result.status == "failed" or result.data is None:
            continue
        if result.tool_name == "compare_aspects" and result.data["groups"]:
            winners = set(result.data["groups"][0]["categories"])
            id_field = "negative_ids" if metric in {"negative_count", "negative_rate"} else "mention_ids"
            ids = {record_id for stat in result.data["stats"] if stat["category"] in winners for record_id in stat[id_field]}
            return ctx.scope(list(ids))
        if result.tool_name == "aggregate_aspects":
            id_field = "negative_ids" if metric in {"negative_count", "negative_rate"} else "mention_ids"
            ids = {record_id for stat in result.data["stats"] for record_id in stat[id_field]}
            return ctx.scope(list(ids))
    return ctx.scope(None)


def _parse_failure(method: str, question_id: str | None, outcome: ParseOutcome, ctx: AnalysisContext) -> AnswerPayload:
    if outcome.status == "unavailable_metadata":
        return AnswerPayload(method=method, question_id=question_id, status="insufficient_info",
                             answer_text=f"Required metadata unavailable: {', '.join(outcome.missing_metadata)}.",
                             coverage=ctx.dataset.coverage, usage={"api_requests": outcome.requests, "parser_requests": outcome.requests})
    return AnswerPayload(method=method, question_id=question_id, status="failed", answer_text="",
                         error_code=outcome.error_code or "query_parse_failed", coverage=ctx.dataset.coverage,
                         usage={"api_requests": outcome.requests, "parser_requests": outcome.requests,
                                "diagnostic": outcome.diagnostic})


def _tool_failure(method: str, question_id: str | None, ctx: AnalysisContext, trace: list[TraceEvent], outcome: ParseOutcome) -> AnswerPayload:
    return AnswerPayload(method=method, question_id=question_id, status="failed", answer_text="",
                         error_code="analysis_tool_failed", coverage=ctx.dataset.coverage, tool_trace=trace,
                         usage={"api_requests": outcome.requests, "parser_requests": outcome.requests, "analysis_tool_calls": len(trace)})
