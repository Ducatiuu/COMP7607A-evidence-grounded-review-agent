import json
from collections import deque

from eval.run_method import main as run_method_main
from src.llm_client import LLMRequest, LLMResponse, MockLLMClient
from src.llm_telemetry import RecordingLLMClient


def test_telemetry_keeps_unknown_usage_null_and_omits_content_by_default(tmp_path):
    path = tmp_path / "calls.jsonl"
    client = RecordingLLMClient(MockLLMClient(deque([
        LLMResponse(content={"status": "ok", "private": "response-secret"}, model="mock", input_tokens=7),
        TimeoutError("transport-secret"),
    ])), path, run_id="run-1", configured_model="mock", config_sha256="a" * 64,
        method="a", question_id="Q1")
    request = LLMRequest(stage="direct_answer", system_prompt="prompt-secret",
                         payload={"question_id": "Q1", "text": "request-secret", "prompt_version": "direct-v1"},
                         schema_name="AnswerPayload")
    assert client.complete_json(request).model == "mock"
    try:
        client.complete_json(request)
    except TimeoutError:
        pass
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and [row["status"] for row in rows] == ["ok", "failed"]
    assert rows[0]["input_tokens"] == 7 and rows[0]["output_tokens"] is None
    assert rows[1]["input_tokens"] is None and rows[1]["cost_usd"] is None
    assert rows[1]["error_type"] == "TimeoutError"
    assert all("request" not in row and "response" not in row for row in rows)
    assert all("secret" not in json.dumps(row) for row in rows)


def test_mock_run_ledger_has_one_telemetry_row_per_actual_request(tmp_path):
    for method, condition, expected in [("a", "main", 1), ("b", "main", 6),
                                         ("c", "main", 8), ("c", "gold", 4)]:
        directory = tmp_path / f"{method}-{condition}"
        args = ["--method", method, "--condition", condition, "--mock", "--out", str(directory)]
        assert run_method_main(args) == 0
        answer_row = json.loads((directory / "answers.jsonl").read_text(encoding="utf-8"))
        calls = [json.loads(line) for line in (directory / "model_calls.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len(calls) == answer_row["api_requests"] == expected
        assert all(row["mode"] == "MOCK" and row["config_sha256"] == answer_row["config_sha256"] for row in calls)
        assert all(row["cost_usd"] is None for row in calls)
        assert all(row["question_id"] is None and row["method"] is None for row in calls if row["stage"] == "extract")
        assert all(row["prompt_version"] == "extract-v1" for row in calls if row["stage"] == "extract")
        assert run_method_main(args) == 0
        assert len((directory / "model_calls.jsonl").read_text(encoding="utf-8").splitlines()) == expected
