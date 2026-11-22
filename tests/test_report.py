import json
from pathlib import Path

import pytest

from eval.questions import GoldReference
from eval.report import summarize_runs
from eval.run_method import main as run_method_main
from eval.runner import RunConfig, RunTask, run_tasks
from scripts.summarize_runs import main as summarize_main
from src.schemas import AnswerPayload, NumericClaim


ROOT = Path(__file__).resolve().parents[1]


def test_report_scores_actual_mock_rows_and_pairs_methods(tmp_path):
    dirs = []
    for method, condition in [("a", "main"), ("b", "main"), ("c", "main"), ("c", "ablation"), ("c", "repeats")]:
        directory = tmp_path / f"{method}-{condition}"
        assert run_method_main(["--method", method, "--condition", condition, "--mock", "--out", str(directory)]) == 0
        dirs.append(directory)
    target = tmp_path / "report.json"
    assert summarize_main(["--runs", *(str(item) for item in dirs), "--references",
                           str(ROOT / "data/demo/core_reference.json"), "--out", str(target)]) == 0
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["mode"] == "MOCK_ONLY_NOT_RESEARCH_RESULT"
    assert report["paired"]["main"]["count"] == 1
    assert report["paired"]["main_vs_ablation_c"]["count"] == 1
    assert report["repeat_variability"]["c"] == {"complete_question_pairs": 1, "status_disagreement_count": 0,
                                                  "primary_success_disagreement_count": 0, "incomplete_question_pairs": 0}
    assert all(item["scores"]["equal_type_average"] == 1 for item in report["runs"])
    assert all(item["cost_usd"] is None for item in report["runs"])
    main_b = next(item for item in report["runs"] if item["condition"] == "main" and item["method"] == "b")
    efficiency = main_b["model_call_efficiency"]
    assert (efficiency["call_rows"], efficiency["extraction_requests"], efficiency["query_requests"],
            efficiency["request_count_agrees"], efficiency["cost_usd"]) == (6, 4, 2, True, None)
    refs = [GoldReference.model_validate(item) for item in json.loads((ROOT / "data/demo/core_reference.json").read_text(encoding="utf-8"))]
    with pytest.raises(ValueError, match="duplicate condition"):
        summarize_runs([dirs[0], dirs[0]], refs)
    row_path = dirs[0] / "answers.jsonl"
    row = json.loads(row_path.read_text(encoding="utf-8"))
    row["question_id"] = "unknown"
    row_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        summarize_runs(dirs, refs)


def test_report_scores_latest_attempt_but_accounts_for_every_retry(tmp_path):
    config = RunConfig(method="b", split="demo", dataset_sha256="a" * 64,
                       question_manifest_sha256="b" * 64, model_id="mock", prompt_version="v1")
    task = RunTask(question_id="demo-rate", pack_id="demo", question="What is the negative service rate?")
    references = [GoldReference.model_validate(item) for item in json.loads(
        (ROOT / "data/demo/core_reference.json").read_text(encoding="utf-8"))]
    calls = 0

    def execute(_task):
        nonlocal calls
        calls += 1
        if calls == 1:
            return AnswerPayload(method="b", question_id=task.question_id, status="failed", answer_text="",
                                 error_code="fixture_failure", usage={"api_requests": 2})
        return AnswerPayload(method="b", question_id=task.question_id, status="ok", answer_text="2 of 3",
                             numeric_claims=[NumericClaim(metric="negative_rate", category="service",
                                                          value=2 / 3, numerator=2, denominator=3)],
                             denominator_explanation="Three service mentions", usage={"api_requests": 3})

    assert run_tasks(config, [task], tmp_path, execute).recorded == 1
    assert run_tasks(config, [task], tmp_path, execute, retry_failed=True).recorded == 1
    assert calls == 2
    report = summarize_runs([tmp_path], references)["runs"][0]
    assert (report["recorded"], report["failed"], report["attempt_rows"],
            report["failed_or_partial_attempt_rows"]) == (1, 0, 2, 1)
    assert report["scores"]["equal_type_average"] == 1
    assert report["api_requests_known"] == 5
    assert report["api_requests_unknown_rows"] == 0
    assert report["cost_usd"] is None
    assert report["model_call_efficiency"] == {"available": False, "reason": "model_calls.jsonl absent"}

    rows_path = tmp_path / "answers.jsonl"
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["cost_usd"], rows[1]["cost_usd"] = 0.25, 0.75
    rows_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert summarize_runs([tmp_path], references)["runs"][0]["cost_usd"] == 1.0

    rows[0]["api_requests"], rows[0]["answer"]["usage"] = None, {}
    rows[0]["cost_usd"] = None
    rows_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    report = summarize_runs([tmp_path], references)["runs"][0]
    assert (report["api_requests_known"], report["api_requests_unknown_rows"], report["cost_usd"]) == (3, 1, None)

    rows[0]["attempt_index"] = 2
    rows_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="nonconsecutive attempts"):
        summarize_runs([tmp_path], references)


def test_report_reconciles_mock_call_telemetry_and_stage_latency(tmp_path):
    assert run_method_main(["--method", "b", "--mock", "--out", str(tmp_path)]) == 0
    references = [GoldReference.model_validate(item) for item in json.loads(
        (ROOT / "data/demo/core_reference.json").read_text(encoding="utf-8"))]
    path = tmp_path / "model_calls.jsonl"
    calls = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 6
    assert [row["stage"] for row in calls] == ["extract"] * 4 + ["query_parse", "answer"]
    for index, row in enumerate(calls, start=1):
        row["latency_ms"] = float(index)
        row["input_tokens"] = 7 if index == 1 else None
        row["cost_usd"] = 0.2
    calls[4].update(status="failed", error_type="TimeoutError", response_model=None,
                    response_sha256=None, input_tokens=None, output_tokens=None, response=None)
    path.write_text("".join(json.dumps(row) + "\n" for row in calls), encoding="utf-8")
    efficiency = summarize_runs([tmp_path], references)["runs"][0]["model_call_efficiency"]
    assert efficiency["available"] and efficiency["request_count_agrees"] is True
    assert (efficiency["call_rows"], efficiency["failed_call_rows"],
            efficiency["extraction_requests"], efficiency["query_requests"]) == (6, 1, 4, 2)
    assert efficiency["extraction_call_latency_ms"] == {"count": 4, "median_ms": 2.5, "p95_ms": 4.0}
    assert efficiency["query_call_latency_ms"] == {"count": 2, "median_ms": 5.5, "p95_ms": 6.0}
    assert efficiency["query_model_latency_per_attempt_ms"] == {"count": 1, "median_ms": 11.0, "p95_ms": 11.0}
    assert (efficiency["input_tokens_known"], efficiency["input_tokens_unknown_calls"],
            efficiency["cost_usd"]) == (7, 5, pytest.approx(1.2))

    calls[0]["cost_usd"] = None
    orphan = {**calls[-1], "run_id": "orphan-run", "call_index": 1}
    calls.append(orphan)
    path.write_text("".join(json.dumps(row) + "\n" for row in calls), encoding="utf-8")
    efficiency = summarize_runs([tmp_path], references)["runs"][0]["model_call_efficiency"]
    assert efficiency["request_count_agrees"] is False
    assert efficiency["physical_minus_answer_requests"] == 1
    assert efficiency["cost_usd"] is None

    calls[-1]["call_index"] = 2
    path.write_text("".join(json.dumps(row) + "\n" for row in calls), encoding="utf-8")
    with pytest.raises(ValueError, match="nonconsecutive model call index"):
        summarize_runs([tmp_path], references)

    calls[-1]["call_index"] = 1
    calls[-1]["config_sha256"] = "f" * 64
    path.write_text("".join(json.dumps(row) + "\n" for row in calls), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match run config"):
        summarize_runs([tmp_path], references)
