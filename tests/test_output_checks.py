from collections import deque
import json

import pytest

from src.llm_client import LLMResponse, MockLLMClient
from src.schemas import AnswerPayload, QuerySpec
from src.tools import dispatch_tool
from src.verification import Finalizer, check_answer
from src.verification.output_checks import supported_comparison_groups, supported_numeric_claims
from test_tools import _dataset


def _rate_context():
    ctx = _dataset()
    result = dispatch_tool(ctx, call_id="a1", name="aggregate_aspects", arguments={"categories": ["service"], "metric": "negative_rate"})
    query = QuerySpec(task_type="rate", categories=["service"], metric="negative_rate", denominator_spec="aspect_mentions")
    return ctx, result, query


def _answer(value=2 / 3, quote=None):
    return {
        "method": "b", "status": "ok", "answer_text": "Service is negative in two of three mentions.",
        "numeric_claims": [{"metric": "negative_rate", "category": "service", "scope_ids": ["R01", "R02", "R03", "R04"], "value": value, "numerator": 2, "denominator": 3, "unit": "fraction"}],
        "denominator_explanation": "Among the three records mentioning service.",
        "citations": [] if quote is None else [{"record_id": "R01", "quote": quote}],
    }


def test_verifier_accepts_actual_rate_and_rejects_wrong_number_or_quote():
    ctx, result, query = _rate_context()
    assert check_answer(AnswerPayload.model_validate(_answer()), ctx, query, [result]) == []
    assert "unsupported_numeric_claim" in check_answer(AnswerPayload.model_validate(_answer(value=0.5)), ctx, query, [result])
    assert "invalid_citation_quote_or_id" in check_answer(AnswerPayload.model_validate(_answer(quote="invented quote")), ctx, query, [result])
    assert "citation_without_evidence_tool" in check_answer(AnswerPayload.model_validate(_answer(quote="service was slow")), ctx, query, [result])
    wrong_denominator_query = QuerySpec(task_type="rate", categories=["service"], metric="negative_rate", denominator_spec="all_records")
    assert "unsupported_numeric_claim" in check_answer(AnswerPayload.model_validate(_answer()), ctx, wrong_denominator_query, [result])


def test_verifier_requires_full_selection_and_tie_groups():
    ctx = _dataset()
    filter_result = dispatch_tool(ctx, call_id="f1", name="filter_records", arguments={"conditions": [{"category": "food", "sentiment": "positive"}]})
    query = QuerySpec(task_type="selection", conditions=[{"category": "food", "sentiment": "positive"}])
    answer = AnswerPayload(method="b", status="ok", answer_text="R01", selected_record_ids=["R01"])
    assert "selection_mismatch" in check_answer(answer, ctx, query, [filter_result])
    comparison = dispatch_tool(ctx, call_id="c1", name="compare_aspects", arguments={"categories": ["service", "food"], "metric": "mention_count"})
    comparison_query = QuerySpec(task_type="comparison", categories=["service", "food"], metric="mention_count")
    answer = AnswerPayload(method="b", status="ok", answer_text="Tied", comparison_groups=[["service"], ["food"]], numeric_claims=[
        {"metric": "mention_count", "category": category, "scope_ids": ["R01", "R02", "R03", "R04"], "value": 3} for category in ["service", "food"]
    ])
    assert "comparison_groups_mismatch" in check_answer(answer, ctx, comparison_query, [comparison])


def test_finalizer_repairs_once_using_real_tool_result():
    ctx, result, query = _rate_context()
    client = MockLLMClient(deque([LLMResponse(content=_answer(0.5), model="mock"), LLMResponse(content=_answer(), model="mock")]))
    answer = Finalizer(client, "mock").finish(method="b", question="Service negative rate?", question_id="Q1", query=query, ctx=ctx, results=[result], trace=[])
    assert answer.status == "ok" and answer.numeric_claims[0].value == 2 / 3
    assert answer.usage["api_requests"] == 2 and answer.usage["output_repairs"] == 1
    assert client.requests[1].stage == "answer_repair"
    assert client.requests[1].payload["validation_errors"] == ["unsupported_numeric_claim"]
    assert answer.usage["attempt_diagnostics"] == [
        {"attempt": 1, "stage": "output_checks", "codes": ["unsupported_numeric_claim"]}]


def test_answer_v2_prompt_contract_and_unsupported_version():
    ctx, result, query = _rate_context()
    client = MockLLMClient(deque([LLMResponse(content=_answer(), model="mock")]))
    answer = Finalizer(client, "mock", prompt_version="answer-v2").finish(
        method="b", question="Service negative rate?", question_id="Q1",
        query=query, ctx=ctx, results=[result], trace=[])
    assert answer.status == "ok"
    request = client.requests[0]
    assert request.payload["prompt_version"] == "answer-v2"
    assert "status" in request.system_prompt and "answer_text" in request.system_prompt
    assert "numeric_claims" in request.system_prompt and "scope_ids" in request.system_prompt
    with pytest.raises(ValueError, match="unsupported answer prompt version"):
        Finalizer(client, "mock", prompt_version="answer-unknown")


def test_answer_v3_supplies_only_tool_supported_target_claims():
    ctx, result, query = _rate_context()
    candidates = supported_numeric_claims(query, [result])
    assert candidates == [{"metric": "negative_rate", "category": "service",
                           "scope_ids": ["R01", "R02", "R03", "R04"], "value": 2 / 3,
                           "numerator": 2, "denominator": 3}]
    wrong_denominator = QuerySpec(task_type="rate", categories=["service"],
                                  metric="negative_rate", denominator_spec="all_records")
    assert supported_numeric_claims(wrong_denominator, [result]) == []
    client = MockLLMClient(deque([LLMResponse(content=_answer(), model="mock")]))
    answer = Finalizer(client, "mock", prompt_version="answer-v3").finish(
        method="b", question="Service negative rate?", question_id="Q1",
        query=query, ctx=ctx, results=[result], trace=[])
    assert answer.status == "ok"
    assert client.requests[0].payload["supported_numeric_claims"] == candidates
    assert "supported_numeric_claims" in client.requests[0].system_prompt


def test_supported_numeric_claim_preserves_empty_filtered_scope():
    ctx = _dataset()
    filtered = dispatch_tool(ctx, call_id="f0", name="filter_records", arguments={
        "conditions": [{"category": "service", "sentiment": "conflict"}]})
    assert filtered.data["record_ids"] == []
    aggregate = dispatch_tool(ctx, call_id="a0", name="aggregate_aspects", arguments={
        "categories": ["service"], "record_ids": filtered.data["record_ids"],
        "metric": "negative_count"})
    query = QuerySpec(task_type="count", conditions=[{"category": "service", "sentiment": "conflict"}],
                      categories=["service"], metric="negative_count")
    assert supported_numeric_claims(query, [filtered, aggregate]) == [{
        "metric": "negative_count", "category": "service", "scope_ids": [],
        "value": 0, "numerator": None, "denominator": None}]


def test_answer_v4_copies_ranked_groups_from_matching_tool():
    ctx = _dataset()
    query = QuerySpec(task_type="comparison", categories=["food", "service"],
                      metric="negative_count")
    result = dispatch_tool(ctx, call_id="c4", name="compare_aspects", arguments={
        "categories": ["food", "service"], "metric": "negative_count"})
    groups = supported_comparison_groups(query, [result])
    assert groups == [group["categories"] for group in result.data["groups"]]
    assert all(isinstance(group, list) for group in groups)
    wrong = QuerySpec(task_type="comparison", categories=["food", "price"],
                      metric="negative_count")
    assert supported_comparison_groups(wrong, [result]) == []
    answer_content = {"status": "ok", "answer_text": "Ranked categories.",
                      "comparison_groups": groups,
                      "numeric_claims": supported_numeric_claims(query, [result])}
    client = MockLLMClient(deque([LLMResponse(content=answer_content, model="mock")]))
    answer = Finalizer(client, "mock", prompt_version="answer-v4").finish(
        method="b", question="Rank food and service", question_id="Q4",
        query=query, ctx=ctx, results=[result], trace=[])
    assert answer.status == "ok" and answer.comparison_groups
    assert client.requests[0].payload["supported_comparison_groups"] == groups


def test_finalizer_fails_after_one_unsuccessful_repair():
    ctx, result, query = _rate_context()
    client = MockLLMClient(deque([LLMResponse(content=_answer(0.5), model="mock"), LLMResponse(content=_answer(0.5), model="mock")]))
    answer = Finalizer(client, "mock").finish(method="b", question="Service negative rate?", question_id="Q1", query=query, ctx=ctx, results=[result], trace=[])
    assert answer.status == "failed" and answer.error_code == "answer_verification_failed"
    assert len(client.requests) == 2
    assert [item["codes"] for item in answer.usage["attempt_diagnostics"]] == [
        ["unsupported_numeric_claim"], ["unsupported_numeric_claim"]]


def test_finalizer_schema_diagnostics_are_redacted_after_failed_repair():
    ctx, result, query = _rate_context()
    invalid = {"status": "ok", "answer_text": "SECRET_REVIEW_TEXT",
               "SECRET_FIELD": "SECRET_MODEL_VALUE"}
    client = MockLLMClient(deque([LLMResponse(content=invalid, model="mock"),
                                  LLMResponse(content=invalid, model="mock")]))
    answer = Finalizer(client, "mock").finish(method="b", question="Service rate?",
                                                question_id="Q1", query=query, ctx=ctx,
                                                results=[result], trace=[])
    assert answer.status == "failed" and answer.usage["output_repairs"] == 1
    diagnostics = answer.usage["attempt_diagnostics"]
    assert len(diagnostics) == 2 and all(item["stage"] == "schema_validation" for item in diagnostics)
    assert all(item["issues"][0]["path"] == "[unrecognized]" for item in diagnostics)
    assert "SECRET" not in json.dumps(diagnostics)


def test_finalizer_does_not_report_zero_tokens_after_transport_failure():
    ctx, result, query = _rate_context()
    client = MockLLMClient(deque([TimeoutError(), LLMResponse(content=_answer(), model="mock", input_tokens=10, output_tokens=5)]))
    answer = Finalizer(client, "mock").finish(method="b", question="Service negative rate?", question_id="Q1", query=query, ctx=ctx, results=[result], trace=[])
    assert answer.status == "ok" and answer.usage["api_requests"] == 2
    assert answer.usage["input_tokens"] is None and answer.usage["output_tokens"] is None


def test_ablation_disables_output_checks_and_repair_but_keeps_schema():
    ctx, result, query = _rate_context()
    client = MockLLMClient(deque([LLMResponse(content=_answer(0.5), model="mock")]))
    answer = Finalizer(client, "mock", verify_outputs=False).finish(method="c", question="Service negative rate?", question_id="Q1", query=query, ctx=ctx, results=[result], trace=[])
    assert answer.status == "ok" and answer.numeric_claims[0].value == 0.5
    assert answer.usage["output_repairs"] == 0 and len(client.requests) == 1
    invalid = MockLLMClient(deque([LLMResponse(content={"status": "ok", "answer_text": "bad", "numeric_claims": [{"metric": "x", "value": "many"}]}, model="mock")]))
    failed = Finalizer(invalid, "mock", verify_outputs=False).finish(method="c", question="?", question_id="Q1", query=query, ctx=ctx, results=[result], trace=[])
    assert failed.status == "failed" and len(invalid.requests) == 1
