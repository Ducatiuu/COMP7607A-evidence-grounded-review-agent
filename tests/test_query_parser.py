from collections import deque
import json

from src.controllers import QueryParser
from src.llm_client import LLMResponse, MockLLMClient


def _client(content, model="mock"):
    return MockLLMClient(deque([LLMResponse(content=content, model=model)]))


def test_shared_parser_uses_one_call_and_preserves_predicate_pairs():
    content = {
        "task_type": "selection", "operator": "AND",
        "conditions": [{"category": "food", "sentiment": "positive"}, {"category": "service", "sentiment": "negative"}],
        "categories": [], "metric": None, "denominator_spec": None,
        "metadata_required": [], "needs_evidence": True,
    }
    client = _client(content)
    outcome = QueryParser(client=client, provider_model="mock").parse("Which reviews praise food but criticize service?")
    assert outcome.status == "ok" and outcome.requests == 1
    assert [(p.category.value, p.sentiment.value) for p in outcome.query.conditions] == [("food", "positive"), ("service", "negative")]
    assert len(client.requests) == 1
    assert "tool order" in client.requests[0].system_prompt


def test_missing_metadata_prevents_analysis():
    content = {"task_type": "rate", "conditions": [], "categories": ["food"], "metric": "negative_rate", "denominator_spec": "all_records", "metadata_required": ["date"], "needs_evidence": False}
    outcome = QueryParser(client=_client(content), provider_model="mock").parse("How did food complaints change by month?")
    assert outcome.status == "unavailable_metadata"
    assert outcome.missing_metadata == ("date",)


def test_invalid_parse_and_model_mismatch_fail_without_retry():
    invalid = _client({"task_type": "selection", "conditions": []})
    outcome = QueryParser(client=invalid, provider_model="mock").parse("Which reviews?")
    assert outcome.status == "failed" and outcome.error_code == "invalid_query_parse"
    assert len(invalid.requests) == 1
    mismatch = _client({"task_type": "insufficient_info"}, model="other")
    assert QueryParser(client=mismatch, provider_model="mock").parse("When?").status == "failed"


def test_empty_question_has_no_model_request():
    client = MockLLMClient()
    outcome = QueryParser(client=client, provider_model="mock").parse("  ")
    assert outcome.error_code == "empty_question" and outcome.requests == 0
    assert client.requests == []


def test_invalid_query_diagnostic_is_structural_and_redacted():
    client = _client({"task_type": "count", "categories": "SECRET_MODEL_TEXT",
                      "SECRET_FIELD": "SECRET_REVIEW_TEXT"})
    outcome = QueryParser(client=client, provider_model="mock").parse("Count service reviews")
    assert outcome.status == "failed" and outcome.diagnostic["stage"] == "schema_validation"
    assert {issue["path"] for issue in outcome.diagnostic["issues"]} == {
        "categories", "[unrecognized]"}
    assert "SECRET" not in json.dumps(outcome.diagnostic)
