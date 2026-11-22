import json

import pytest
from pydantic import ValidationError

from eval.runner import RunConfig, RunTask, run_tasks
from src.schemas import AnswerPayload


def _config(**changes):
    base = {"method": "b", "split": "demo", "condition": "main", "dataset_sha256": "a" * 64,
            "question_manifest_sha256": "b" * 64, "model_id": "mock", "prompt_version": "v1", "mock": True}
    return RunConfig(**{**base, **changes})


def _tasks():
    return [RunTask(question_id="Q1", pack_id="P1", question="first"), RunTask(question_id="Q2", pack_id="P1", question="second")]


def _answer(task, status="ok", requests=2, cost=None):
    usage = {"api_requests": requests}
    if cost is not None:
        usage["cost_usd"] = cost
    return AnswerPayload(method="b", question_id=task.question_id, status=status, answer_text="answer" if status == "ok" else "",
                         error_code="fixture_error" if status == "failed" else None, usage=usage)


def test_resume_keeps_failures_and_explicit_retry_appends_attempt(tmp_path):
    calls = []

    def execute(task):
        calls.append(task.key)
        return _answer(task, "failed" if task.question_id == "Q2" and calls.count(task.key) == 1 else "ok")

    first = run_tasks(_config(), _tasks(), tmp_path, execute)
    assert first.recorded == 2 and first.retained_failures == 0
    second = run_tasks(_config(), _tasks(), tmp_path, execute)
    assert second.recorded == 0 and second.skipped_existing == 1 and second.retained_failures == 1
    assert calls == [_tasks()[0].key, _tasks()[1].key]
    third = run_tasks(_config(), _tasks(), tmp_path, execute, retry_failed=True)
    assert third.recorded == 1 and calls == [_tasks()[0].key, _tasks()[1].key, _tasks()[1].key]
    rows = [json.loads(line) for line in (tmp_path / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(row["question_id"], row["status"], row["attempt_index"]) for row in rows] == [("Q1", "ok", 1), ("Q2", "failed", 1), ("Q2", "ok", 2)]
    assert all(row["mode"] == "MOCK" and row["cost_usd"] is None for row in rows)


def test_resume_rejects_config_or_task_mismatch(tmp_path):
    run_tasks(_config(), _tasks(), tmp_path, lambda task: _answer(task))
    with pytest.raises(ValueError, match="manifest/config/task list mismatch"):
        run_tasks(_config(model_id="different"), _tasks(), tmp_path, lambda task: _answer(task))
    with pytest.raises(ValueError, match="manifest/config/task list mismatch"):
        run_tasks(_config(), _tasks()[:1], tmp_path, lambda task: _answer(task))
    changed_wording = [RunTask(question_id="Q1", pack_id="P1", question="changed"), _tasks()[1]]
    with pytest.raises(ValueError, match="manifest/config/task list mismatch"):
        run_tasks(_config(), changed_wording, tmp_path, lambda task: _answer(task))
    with pytest.raises(ValueError, match="duplicate task key"):
        run_tasks(_config(), [_tasks()[0], _tasks()[0]], tmp_path / "other", lambda task: _answer(task))


def test_request_budget_stops_before_next_task_and_resume_is_idempotent(tmp_path):
    config = _config(max_api_requests=2, estimated_requests_per_task=2)
    calls = []

    def execute(task):
        calls.append(task.question_id)
        return _answer(task, requests=2)

    first = run_tasks(config, _tasks(), tmp_path, execute)
    assert (first.recorded, first.pending, first.budget_stopped) == (1, 1, True)
    second = run_tasks(config, _tasks(), tmp_path, execute)
    assert (second.recorded, second.skipped_existing, second.pending) == (0, 1, 1)
    assert calls == ["Q1"]


@pytest.mark.parametrize("requests", [None, 2, True, -1])
def test_request_cap_stops_after_unknown_or_underestimated_usage_in_same_run(tmp_path, requests):
    config = _config(max_api_requests=5, estimated_requests_per_task=1)
    calls = []

    def execute(task):
        calls.append(task.question_id)
        if requests is None:
            raise TimeoutError()
        return _answer(task, requests=requests)

    summary = run_tasks(config, _tasks(), tmp_path, execute)
    assert (summary.recorded, summary.pending, summary.budget_stopped) == (1, 1, True)
    assert calls == ["Q1"]
    rows = [json.loads(line) for line in (tmp_path / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["api_requests"] == (2 if requests == 2 else None)
    if requests != 2:
        with pytest.raises(ValueError, match="unknown prior usage"):
            run_tasks(config, _tasks(), tmp_path, execute)
        if requests is True:
            rows[0]["api_requests"] = 1
            (tmp_path / "answers.jsonl").write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
            with pytest.raises(ValueError, match="invalid JSONL row"):
                run_tasks(config, _tasks(), tmp_path, execute)
    else:
        with pytest.raises(ValueError, match="per-task estimate was exceeded"):
            run_tasks(config, _tasks(), tmp_path, execute)


def test_request_stop_counts_pending_explicit_retry(tmp_path):
    config = _config(max_api_requests=5, estimated_requests_per_task=1)
    summary = run_tasks(config, _tasks()[:1], tmp_path, lambda task: _answer(task, "failed", True),
                        retry_failed=True)
    assert (summary.recorded, summary.pending, summary.budget_stopped) == (1, 1, True)


def test_cost_cap_preflight_uses_known_cumulative_fee(tmp_path):
    config = _config(max_cost_usd=0.5, estimated_cost_per_task_usd=0.3)
    calls = []

    def execute(task):
        calls.append(task.question_id)
        return _answer(task, cost=0.1)

    summary = run_tasks(config, _tasks(), tmp_path, execute)
    assert (summary.recorded, summary.pending, summary.budget_stopped) == (2, 0, False)
    assert calls == ["Q1", "Q2"]
    rows = [json.loads(line) for line in (tmp_path / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["cost_usd"] for row in rows] == [0.1, 0.1]
    blocked = run_tasks(config, _tasks(), tmp_path / "blocked", lambda task: _answer(task, cost=0.3))
    assert (blocked.recorded, blocked.pending, blocked.budget_stopped) == (1, 1, True)


def test_cost_cap_decimal_boundary_is_not_lost_to_float_rounding(tmp_path):
    config = _config(max_cost_usd=0.3, estimated_cost_per_task_usd=0.2)
    summary = run_tasks(config, _tasks(), tmp_path, lambda task: _answer(task, cost=0.1))
    assert (summary.recorded, summary.pending, summary.budget_stopped) == (2, 0, False)


@pytest.mark.parametrize("cost", [None, 0.5, True, -0.1])
def test_cost_cap_stops_after_unknown_or_over_bound_fee(tmp_path, cost):
    config = _config(max_cost_usd=1.0, estimated_cost_per_task_usd=0.4)
    calls = []

    def execute(task):
        calls.append(task.question_id)
        return _answer(task, cost=cost)

    summary = run_tasks(config, _tasks(), tmp_path, execute)
    assert (summary.recorded, summary.pending, summary.budget_stopped) == (1, 1, True)
    assert calls == ["Q1"]
    row = json.loads((tmp_path / "answers.jsonl").read_text(encoding="utf-8"))
    assert row["cost_usd"] == (0.5 if cost == 0.5 else None)
    message = "per-task estimate was exceeded" if cost == 0.5 else "unknown prior cost"
    with pytest.raises(ValueError, match=message):
        run_tasks(config, _tasks(), tmp_path, execute)
    if cost is True:
        row["cost_usd"] = 1.0
        (tmp_path / "answers.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="invalid JSONL row"):
            run_tasks(config, _tasks(), tmp_path, execute)


def test_cost_stop_counts_pending_explicit_retry(tmp_path):
    config = _config(max_cost_usd=1.0, estimated_cost_per_task_usd=0.4)
    summary = run_tasks(config, _tasks()[:1], tmp_path, lambda task: _answer(task, "failed"), retry_failed=True)
    assert (summary.recorded, summary.pending, summary.budget_stopped) == (1, 1, True)


def test_cost_cap_counts_failed_attempt_before_explicit_retry(tmp_path):
    config = _config(max_cost_usd=0.5, estimated_cost_per_task_usd=0.3)
    calls = 0

    def execute(task):
        nonlocal calls
        calls += 1
        return _answer(task, "failed" if calls == 1 else "ok", cost=0.2)

    first = run_tasks(config, _tasks()[:1], tmp_path, execute)
    second = run_tasks(config, _tasks()[:1], tmp_path, execute, retry_failed=True)
    assert first.recorded == second.recorded == 1 and calls == 2
    rows = [json.loads(line) for line in (tmp_path / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(row["status"], row["cost_usd"]) for row in rows] == [("failed", 0.2), ("ok", 0.2)]


def test_failed_execution_is_row_and_unknown_usage_blocks_budgeted_resume(tmp_path):
    config = _config(max_api_requests=3, estimated_requests_per_task=1)

    def execute(_task):
        raise TimeoutError()

    first = run_tasks(config, _tasks()[:1], tmp_path, execute)
    assert first.recorded == 1
    row = json.loads((tmp_path / "answers.jsonl").read_text(encoding="utf-8"))
    assert row["status"] == "failed" and row["api_requests"] is None
    with pytest.raises(ValueError, match="unknown prior usage"):
        run_tasks(config, _tasks()[:1], tmp_path, execute, retry_failed=True)


def test_live_mode_and_gold_fields_are_rejected():
    with pytest.raises(ValidationError, match="live execution"):
        _config(mock=False)
    with pytest.raises(ValidationError):
        RunTask(question_id="Q1", pack_id="P1", question="?", gold_answer=2)
    with pytest.raises(ValidationError):
        _config(max_cost_usd=float("inf"), estimated_cost_per_task_usd=0.1)


def test_insufficient_info_is_terminal_and_tampered_row_is_rejected(tmp_path):
    task = RunTask(question_id="Q1", pack_id="P1", question="When?")
    calls = []

    def execute(item):
        calls.append(item.key)
        return AnswerPayload(method="b", question_id=item.question_id, status="insufficient_info", answer_text="No dates")

    first = run_tasks(_config(), [task], tmp_path, execute)
    second = run_tasks(_config(), [task], tmp_path, execute)
    assert first.recorded == 1 and second.skipped_existing == 1 and calls == [task.key]
    path = tmp_path / "answers.jsonl"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["status"] = "ok"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSONL row"):
        run_tasks(_config(), [task], tmp_path, execute)
