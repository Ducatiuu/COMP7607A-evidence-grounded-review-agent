import json

import pytest

from scripts.plan_dev_pilot import build_plan, main
from scripts.prepare_dev_pilot import main as prepare_main
from test_prepare_dev_pilot import _args as prepare_args, _sources


def _prepared(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    assert prepare_main(prepare_args(tmp_path, _sources(tmp_path))) == 0
    return {
        "manifest_path": tmp_path / "pilot" / "manifest.json",
        "csv_path": tmp_path / "pilot" / "pilot.csv",
        "questions_path": tmp_path / "pilot" / "questions.json",
        "references_path": tmp_path / "gold" / "references.json",
        "split_path": tmp_path / "split.json",
        "run_dir": tmp_path / "unused_run",
        "provider": "deepseek", "model": "deepseek-flash",
        "max_input_chars": 10000, "max_input_tokens": 8192,
        "max_output_tokens": 2048, "max_cost_usd": "1.00",
        "input_usd_per_million": "0.3", "output_usd_per_million": "1.2",
        "price_source": "fixture://offline-prices", "price_date": "2026-11-23",
        "timeout_seconds": 45,
    }


def test_plan_binds_dev_inputs_and_conservative_full_pilot_budget(tmp_path, capsys):
    kwargs = _prepared(tmp_path)
    capsys.readouterr()
    plan = build_plan(**kwargs)
    assert (plan["status"], plan["network_calls_made"], plan["record_count"], plan["question_count"]) == (
        "DRY_RUN_APPROVAL_REQUIRED", 0, 30, 10)
    assert not plan["execution_runner_ready"]
    assert plan["shared_extraction_request_bound"] == 60
    assert plan["method_request_bounds"] == {"a": 10, "b": 30, "c": 70}
    assert plan["max_api_requests"] == 170 and plan["declared_worst_case_usd"] == "0.835584"
    assert plan["data_scope"] == "TRAIN_DERIVED_DEV_ONLY" and not plan["candidate_review_complete"]
    assert "count" not in plan and "source_record_ids" not in plan
    assert build_plan(**kwargs)["plan_sha256"] == plan["plan_sha256"]
    assert not kwargs["run_dir"].exists()


def test_plan_rejects_changed_files_or_existing_run_before_any_call(tmp_path, capsys):
    kwargs = _prepared(tmp_path)
    capsys.readouterr()
    kwargs["references_path"].write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="hashes"):
        build_plan(**kwargs)
    kwargs = _prepared(tmp_path / "second")
    capsys.readouterr()
    kwargs["run_dir"].mkdir()
    with pytest.raises(ValueError, match="already exists"):
        build_plan(**kwargs)


def test_cli_writes_only_new_local_plan_and_never_executes(tmp_path, capsys):
    kwargs = _prepared(tmp_path)
    capsys.readouterr()
    output = tmp_path / "plan.json"
    args = ["--manifest", str(kwargs["manifest_path"]), "--csv", str(kwargs["csv_path"]),
            "--questions", str(kwargs["questions_path"]),
            "--references", str(kwargs["references_path"]), "--split", str(kwargs["split_path"]),
            "--run-dir", str(kwargs["run_dir"]), "--out", str(output),
            "--provider", kwargs["provider"], "--model", kwargs["model"],
            "--max-input-chars", str(kwargs["max_input_chars"]),
            "--max-input-tokens-per-request", str(kwargs["max_input_tokens"]),
            "--max-output-tokens", str(kwargs["max_output_tokens"]),
            "--max-cost-usd", kwargs["max_cost_usd"],
            "--input-usd-per-million", kwargs["input_usd_per_million"],
            "--output-usd-per-million", kwargs["output_usd_per_million"],
            "--price-source", kwargs["price_source"], "--price-date", kwargs["price_date"]]
    assert main(args) == 0
    printed = json.loads(capsys.readouterr().out)
    assert json.loads(output.read_text(encoding="utf-8"))["plan_sha256"] == printed["plan_sha256"]
    assert printed["network_calls_made"] == 0
    with pytest.raises(FileExistsError):
        main(args)
