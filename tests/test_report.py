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
