import json

import pytest

from scripts.plan_dev_pilot import build_plan
from scripts.prepare_dev_pilot import main as prepare_main
from scripts.run_dev_pilot import checked_plan, main, run_pilot
from src.llm_client import LLMResponse
from test_prepare_dev_pilot import _args as prepare_args, _sources


def _fixture(tmp_path, capsys):
    assert prepare_main(prepare_args(tmp_path, _sources(tmp_path))) == 0
    capsys.readouterr()
    paths = {
        "manifest_path": tmp_path / "pilot" / "manifest.json",
        "csv_path": tmp_path / "pilot" / "pilot.csv",
        "questions_path": tmp_path / "pilot" / "questions.json",
        "references_path": tmp_path / "gold" / "references.json",
        "split_path": tmp_path / "split.json",
    }
    plan = build_plan(**paths, run_dir=tmp_path / "live_run", provider="deepseek",
                      model="deepseek-flash", max_input_chars=10000,
                      max_input_tokens=8192, max_output_tokens=2048,
                      max_cost_usd="1.00", input_usd_per_million="0.3",
                      output_usd_per_million="1.2", price_source="fixture://prices",
                      price_date="2026-11-23", timeout_seconds=45)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return paths, plan_path, plan


class FakeProvider:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def complete_json(self, request):
        self.calls.append(request)
        if self.fail:
            raise TimeoutError("SECRET_MODEL_CONTENT_MUST_NOT_APPEAR")
        if request.stage == "extract":
            content = {"record_id": request.payload["record_id"],
                       "aspects": [], "status": "ok", "error": None}
        elif request.stage == "direct_answer":
            content = {"status": "ok", "answer_text": "Offline fixture only."}
        elif request.stage == "query_parse":
            content = {"task_type": "insufficient_info", "metadata_required": ["date"]}
        else:
            raise AssertionError(request.stage)
        return LLMResponse(content=content, model="deepseek-flash",
                           input_tokens=10, output_tokens=5)


def test_dry_run_rechecks_hashes_and_never_uses_provider(tmp_path, capsys, monkeypatch):
    paths, plan_path, plan = _fixture(tmp_path, capsys)
    args = ["--plan", str(plan_path), "--manifest", str(paths["manifest_path"]),
            "--csv", str(paths["csv_path"]), "--questions", str(paths["questions_path"]),
            "--references", str(paths["references_path"]), "--split", str(paths["split_path"])]
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["network_calls_made"] == 0
    assert not (tmp_path / "live_run").exists()
    assert checked_plan(plan_path, **paths) == plan
    assert main([*args, "--execute"]) == 2
    assert main([*args, "--execute", "--plan-sha256", "wrong"]) == 2
    assert not (tmp_path / "live_run").exists()
    capsys.readouterr()
    paths["references_path"].write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="hashes"):
        checked_plan(plan_path, **paths)


def test_one_shared_extraction_and_all_thirty_method_answers(tmp_path, capsys):
    paths, plan_path, plan = _fixture(tmp_path, capsys)
    fake = FakeProvider()
    summary = run_pilot(checked_plan(plan_path, **paths), csv_path=paths["csv_path"],
                        questions_path=paths["questions_path"], client=fake)
    assert (summary["status"], summary["completed_method_questions"],
            summary["actual_requests"], summary["recorded_transport_calls"]) == (
                "COMPLETE", 30, 60, 60)
    assert summary["answer_status_counts"] == {"ok": 10, "insufficient_info": 20}
    assert summary["unexpected_status_count"] > 0
    assert not summary["execution_checks_pass"] and not summary["pilot_scored_against_references"]
    assert [call.stage for call in fake.calls].count("extract") == 30
    assert [call.stage for call in fake.calls].count("direct_answer") == 10
    assert [call.stage for call in fake.calls].count("query_parse") == 20
    run_dir = tmp_path / "live_run"
    results = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines()]
    assert len(results) == 30 and {row["method"] for row in results} == {"a", "b", "c"}
    assert all(row["requests"] == 1 for row in results)
    events = [json.loads(line) for line in (run_dir / "calls.jsonl").read_text().splitlines()]
    assert len(events) == 120 and events[0]["event"] == "begin" and events[-1]["event"] == "end"
    assert (run_dir / "summary.json").exists() and (run_dir / "extractions.json").exists()
    with pytest.raises(ValueError, match="already exists"):
        checked_plan(plan_path, **paths)


def test_failed_transport_is_recorded_and_frozen_without_leaking_text(tmp_path, capsys):
    paths, plan_path, _ = _fixture(tmp_path, capsys)
    fake = FakeProvider(fail=True)
    summary = run_pilot(checked_plan(plan_path, **paths), csv_path=paths["csv_path"],
                        questions_path=paths["questions_path"], client=fake)
    assert summary["status"] == "PARTIAL" and summary["reason"] == "GLOBAL_GATE_FROZEN"
    assert summary["actual_requests"] == summary["recorded_transport_calls"] == 1
    assert summary["completed_method_questions"] == 0
    assert not summary["execution_checks_pass"]
    audit = (tmp_path / "live_run" / "calls.jsonl").read_text()
    assert "SECRET_MODEL_CONTENT_MUST_NOT_APPEAR" not in audit
    assert '"event":"begin"' in audit and '"outcome":"error"' in audit
    with pytest.raises(ValueError, match="already exists"):
        checked_plan(plan_path, **paths)
