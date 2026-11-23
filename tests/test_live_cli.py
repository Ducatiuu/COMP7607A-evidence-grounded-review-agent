import json
from collections import deque

from src.data_loader import load_csv
from src.live_cli import main
from src.llm_client import LLMResponse, MockLLMClient


def _args(path, command="ask", *, execute=False, max_cost="0.015", max_requests=None):
    args = [command, "--input", str(path), "--text-column", "review",
            "--provider", "openai", "--model", "model-one",
            "--max-records", "1", "--max-input-chars", "1000",
            "--max-api-requests", str(max_requests if max_requests is not None else (5 if command == "ask" else 2)),
            "--max-input-tokens-per-request", "1000", "--max-output-tokens", "1000",
            "--max-cost-usd", max_cost, "--input-usd-per-million", "1",
            "--output-usd-per-million", "2", "--price-source", "fixture://not-a-quote",
            "--price-date", "2026-11-22"]
    if command == "ask":
        args += ["--method", "b", "--question", "How many negative service reviews?"]
    if execute:
        args.append("--execute")
    return args


def _reply(content):
    return LLMResponse(content=content, model="model-one", input_tokens=10, output_tokens=5)


def test_dry_run_checks_custom_csv_and_budget_without_key(tmp_path, monkeypatch, capsys):
    path = tmp_path / "reviews.csv"
    path.write_text("review,rating\nSlow service.,1\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert main(_args(path)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "DRY_RUN" and result["record_count"] == 1
    assert result["conservative_requests"] == 5
    assert result["declared_worst_case_usd"] == "0.015"


def test_inadequate_budget_or_missing_key_never_calls_provider(tmp_path, monkeypatch, capsys):
    path = tmp_path / "reviews.csv"
    path.write_text("review\nSlow service.\n", encoding="utf-8")
    assert main(_args(path, max_cost="0.014")) == 2
    assert "worst case" in capsys.readouterr().err
    assert main(_args(path, max_requests=4)) == 2
    assert "conservative 5-request bound" in capsys.readouterr().err
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert main(_args(path, execute=True)) == 2
    assert "OPENAI_API_KEY is not set" in capsys.readouterr().err


def test_execute_path_uses_injected_provider_for_non_demo_csv(tmp_path, monkeypatch, capsys):
    path = tmp_path / "reviews.csv"
    path.write_text("review\nSlow service.\n", encoding="utf-8")
    record_id = load_csv(path, text_column="review").records[0].record_id
    fixture = MockLLMClient(deque([
        _reply({"record_id": record_id, "status": "ok", "error": None,
                "aspects": [{"category": "service", "sentiment": "negative", "evidence": ["Slow service"]}]}),
        _reply({"task_type": "count", "categories": ["service"], "metric": "negative_count"}),
        _reply({"status": "ok", "answer_text": "One negative service review.",
                "numeric_claims": [{"metric": "negative_count", "category": "service",
                                    "scope_ids": [record_id], "value": 1}]}),
    ]))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-do-not-use")
    monkeypatch.setattr("src.live_cli.ResponsesClient", lambda *args, **kwargs: fixture)
    assert main(_args(path, execute=True)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "LIVE" and result["actual_requests"] == 3
    assert result["answer"]["status"] == "ok"
    assert result["answer"]["numeric_claims"][0]["value"] == 1
    assert result["extraction_coverage"] == {"total": 1, "success": 1, "failed_ids": []}
    assert [request.stage for request in fixture.requests] == ["extract", "query_parse", "answer"]


def test_extract_command_reports_model_aspects_without_mock_fixture(tmp_path, monkeypatch, capsys):
    path = tmp_path / "reviews.csv"
    path.write_text("review\nSlow service.\n", encoding="utf-8")
    record_id = load_csv(path, text_column="review").records[0].record_id
    fixture = MockLLMClient(deque([_reply({"record_id": record_id, "status": "ok", "error": None,
                                         "aspects": [{"category": "service", "sentiment": "negative",
                                                      "evidence": ["Slow service"]}]})]))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-do-not-use")
    monkeypatch.setattr("src.live_cli.ResponsesClient", lambda *args, **kwargs: fixture)
    assert main(_args(path, command="extract", execute=True)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["actual_requests"] == 1
    assert result["extractions"][0]["aspects"][0]["evidence"] == ["Slow service"]


def test_live_direct_schema_failure_retains_safe_diagnostics_and_usage(tmp_path, monkeypatch, capsys):
    path = tmp_path / "reviews.csv"
    path.write_text("review\nSlow service.\n", encoding="utf-8")
    fixture = MockLLMClient(deque([_reply({"status": "ok", "answer_text": "one",
                                          "unexpected private field": "private response text"})]))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-do-not-use")
    monkeypatch.setattr("src.live_cli.ResponsesClient", lambda *args, **kwargs: fixture)
    args = _args(path, execute=True, max_cost="0.003", max_requests=1)
    args[args.index("--method") + 1] = "a"
    assert main(args) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["actual_requests"] == 1
    assert (result["input_tokens"], result["output_tokens"]) == (10, 5)
    assert result["answer"]["error_code"] == "invalid_direct_answer"
    assert result["answer"]["usage"]["diagnostic"]["stage"] == "schema_validation"
    assert "private response text" not in json.dumps(result)
    assert "unexpected private field" not in json.dumps(result)
    assert len(fixture.requests) == 1
