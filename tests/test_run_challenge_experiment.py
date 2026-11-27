import hashlib
import json
import shutil
from collections import deque
from pathlib import Path

import pytest

from scripts.run_challenge_experiment import build_plan, checked_plan, main, run_challenge
from scripts.plan_challenge_experiment import main as plan_main
from src.llm_client import LLMResponse, MockLLMClient


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fixture(tmp_path, monkeypatch):
    project_root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(tmp_path)
    for filename in ("eval/challenge_metrics.py", "src/absa_service/extractor.py"):
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project_root / filename, target)
    review_dir = tmp_path / "outputs/challenge_label_review_2026-11-27"
    review_dir.mkdir(parents=True)
    source_hashes = {}
    for stem in ("R1_original_paste", "R2_original_paste", "R1_parsed", "R2_parsed", "comparison_40"):
        ext = ".txt" if "original" in stem else ".json"
        path = review_dir / (stem + ext)
        path.write_text(stem, encoding="utf-8")
        source_hashes[stem] = _sha(path)
    pairs = []
    refs = []
    for n in range(1, 41):
        pid = f"CH{n:03d}"
        pairs.append({"pair_id": pid, "source": {"record_id": pid + "-A", "text": "The food was good."},
                      "edited": {"record_id": pid + "-B", "text": "The food was bad."},
                      "text_origin": "CODEX_DRAFT_HUMAN_REVIEWED"})
        refs.append({"pair_id": pid,
                     "source_gold": {"record_id": pid + "-A", "aspects": [{"category": "food", "sentiment": "positive"}]},
                     "edited_gold": {"record_id": pid + "-B", "aspects": [{"category": "food", "sentiment": "negative"}]},
                     "intended_change_categories": ["food"], "stable_categories": [],
                     "subgroup_tags": ["negation"], "provenance": "HUMAN_ADJUDICATED",
                     "independent_reviewer_ids": ["R1", "R2"], "adjudicator_id": "owner",
                     "annotation_record_sha256": "a" * 64})
    pairs_path = tmp_path / "data/challenge/final_text_2026-11-27/final_candidate_pairs.json"
    refs_path = tmp_path / "data/gold/challenge_40_2026-11-27/references.json"
    owner_path = refs_path.parent / "owner_adjudication.json"
    release_path = refs_path.parent / "release.json"
    _write(owner_path, {"status": "OWNER_ADJUDICATED"})
    for ref in refs:
        ref["annotation_record_sha256"] = _sha(owner_path)
    _write(pairs_path, {"pairs": pairs})
    _write(refs_path, refs)
    parsed = {ref["pair_id"]: {"source_labels": {"food": "positive"},
                              "edited_labels": {"food": "negative"},
                              "computed_changed_categories": ["food"],
                              "computed_stable_categories": []} for ref in refs}
    for number in (1, 2):
        path = review_dir / f"R{number}_parsed.json"
        _write(path, parsed)
        source_hashes[f"R{number}_parsed"] = _sha(path)
    source_hashes["final_candidate_pairs"] = _sha(pairs_path)
    _write(release_path, {"status": "HUMAN_ADJUDICATED_GOLD_FROZEN", "pair_count": 40,
                          "source_record_count": 80, "model_run_status": "NOT_RUN",
                          "reviewer_ids": ["R1", "R2"], "adjudicator_id": "owner",
                          "ambiguity_retained_pair_ids": ["CH023"],
                          "source_sha256": source_hashes, "references_sha256": _sha(refs_path),
                          "owner_adjudication_sha256": _sha(owner_path),
                          "scorer_source_sha256": _sha(tmp_path / "eval/challenge_metrics.py"),
                          "changed_category_units": 40, "stable_category_units": 0})
    plan_path = tmp_path / "outputs/challenge_plan.json"
    kwargs = {"pairs_path": pairs_path, "references_path": refs_path, "release_path": release_path,
              "run_dir": Path("outputs/challenge_run"), "model": "deepseek-flash",
              "max_requests": 160, "max_input_tokens": 8192, "max_output_tokens": 2048,
              "max_cost_usd": "3", "input_usd_per_million": "0.3",
              "output_usd_per_million": "1.2", "price_source": "synthetic test price assumption",
              "price_date": "2026-11-27", "timeout_seconds": 45.0}
    _write(plan_path, build_plan(**kwargs))
    return plan_path, kwargs


def _responses():
    return deque(LLMResponse(model="deepseek-flash", content={"record_id": f"CH{n:03d}-{side}",
        "status": "ok", "error": None,
        "aspects": [{"category": "food", "sentiment": "positive" if side == "A" else "negative",
                     "evidence": ["food was good" if side == "A" else "food was bad"]}]},
        input_tokens=50, output_tokens=25, latency_ms=1)
        for n in range(1, 41) for side in ("A", "B"))


def test_preflight_and_complete_offline_run_with_safe_resume(tmp_path, monkeypatch, capsys):
    plan_path, _ = _fixture(tmp_path, monkeypatch)
    plan, _ = checked_plan(plan_path)
    assert main(["--plan", str(plan_path)]) == 0
    assert "PREFLIGHT_ONLY" in capsys.readouterr().out
    client = MockLLMClient(_responses())
    with pytest.raises(ValueError, match="authorization"):
        run_challenge(plan_path, client=client)
    assert len(client.requests) == 0
    partial = run_challenge(plan_path, client=client, authorized=True, max_records=1)
    assert partial["status"] == "PAUSED" and partial["completed_records"] == 1
    result = run_challenge(plan_path, client=client, authorized=True, resume=True)
    assert result["status"] == "COMPLETE" and result["completed_records"] == 80
    assert result["recorded_requests"] == 80 and result["failed_extractions"] == 0
    assert result["input_tokens"] == 4000 and result["output_tokens"] == 2000
    assert len(client.requests) == 80
    assert all("gold" not in json.dumps(request.payload).lower() for request in client.requests)
    prediction_paths = sorted((tmp_path / "outputs/challenge_run/predictions").glob("*.json"))
    assert len(prediction_paths) == 40
    assert json.loads(prediction_paths[0].read_text(encoding="utf-8"))["mode"] == "MOCK"
    assert plan["gold_used_by_model"] is False


def test_changed_hash_and_missing_review_block_preflight(tmp_path, monkeypatch):
    plan_path, kwargs = _fixture(tmp_path, monkeypatch)
    kwargs["pairs_path"].write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        checked_plan(plan_path)
    with pytest.raises(ValueError, match="hash mismatch"):
        build_plan(**kwargs)


def test_unmatched_call_or_inflight_task_blocks_resume(tmp_path, monkeypatch):
    plan_path, _ = _fixture(tmp_path, monkeypatch)
    run_challenge(plan_path, client=MockLLMClient(_responses()), authorized=True, max_records=1)
    tasks = tmp_path / "outputs/challenge_run/tasks.jsonl"
    with tasks.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": "begin", "task_id": "CH001-B"}) + "\n")
    with pytest.raises(ValueError, match="in-flight"):
        run_challenge(plan_path, client=MockLLMClient(_responses()), authorized=True, resume=True)


def test_budget_and_live_cli_gate(tmp_path, monkeypatch, capsys):
    plan_path, kwargs = _fixture(tmp_path, monkeypatch)
    with pytest.raises(Exception, match="worst case exceeds cost cap"):
        build_plan(**{**kwargs, "max_cost_usd": "0.01"})
    assert main(["--plan", str(plan_path), "--execute"]) == 2
    assert "authorization" in capsys.readouterr().err
    assert not (tmp_path / "outputs/challenge_run").exists()


def test_plan_cli_creates_only_a_new_local_file(tmp_path, monkeypatch, capsys):
    _, kwargs = _fixture(tmp_path, monkeypatch)
    args = ["--pairs", str(kwargs["pairs_path"]), "--references", str(kwargs["references_path"]),
            "--release", str(kwargs["release_path"]), "--run-dir", "outputs/another_run",
            "--out", "outputs/another_plan.json", "--max-cost-usd", "3",
            "--input-usd-per-million", "0.3", "--output-usd-per-million", "1.2",
            "--price-source", "synthetic test price assumption", "--price-date", "2026-11-27"]
    assert plan_main(args) == 0
    assert "network_calls_made" in capsys.readouterr().out
    assert checked_plan(Path("outputs/another_plan.json"))[0]["record_count"] == 80
    assert plan_main(args) == 2
    assert "new local outputs path" in capsys.readouterr().err
