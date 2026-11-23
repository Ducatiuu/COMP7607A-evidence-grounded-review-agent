import csv
import hashlib
import json

import pytest

from scripts.score_dev_pilot import _checked_ledger, score_pilot


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    csv_path = tmp_path / "pilot.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["record_id", "text"])
        writer.writeheader()
        writer.writerow({"record_id": "R1", "text": "Service was slow."})
    questions = _write_json(tmp_path / "questions.json", [{
        "question_id": "Q1", "pack_id": "DEV-PILOT", "record_ids": ["R1"],
        "task_type": "count", "wording": "How many negative service reviews?",
        "expected_fields": ["count"], "status": "CANDIDATE_UNREVIEWED",
    }])
    refs = _write_json(tmp_path / "refs.json", [{
        "question_id": "Q1", "task_type": "count", "count": 1,
        "status": "CANDIDATE_UNREVIEWED",
    }])
    gold = _write_json(tmp_path / "gold.json", [{
        "record_id": "R1", "aspects": [{"category": "service", "sentiment": "negative"}],
    }])
    manifest = _write_json(tmp_path / "manifest.json", {
        "status": "DEV_PILOT_CANDIDATE_UNREVIEWED", "human_review_complete": False,
        "record_ids": ["R1"], "question_ids": ["Q1"], "dev_gold_sha256": _hash(gold),
    })
    plan = {
        "planned_run_directory": str(run), "data_scope": "TRAIN_DERIVED_DEV_ONLY",
        "candidate_review_complete": False, "record_count": 1, "question_count": 1,
        "pilot_manifest_sha256": _hash(manifest), "pilot_csv_sha256": _hash(csv_path),
        "questions_sha256": _hash(questions), "references_sha256": _hash(refs),
    }
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    plan["plan_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    plan_path = _write_json(tmp_path / "plan.json", plan)
    _write_json(run / "run_manifest.json", {
        "status": "IN_PROGRESS", "plan_sha256": plan["plan_sha256"],
        "data_scope": "TRAIN_DERIVED_DEV_ONLY",
    })
    _write_json(run / "summary.json", {
        "status": "COMPLETE", "execution_checks_pass": True,
        "pilot_scored_against_references": False, "plan_sha256": plan["plan_sha256"],
        "actual_requests": 4, "recorded_transport_calls": 4,
        "input_tokens": 8, "output_tokens": 4,
        "completed_method_questions": 3, "planned_method_questions": 3,
        "answer_status_counts": {"ok": 3},
    })
    ledger = []
    for call_id in range(1, 5):
        event = {"call_id": call_id, "stage": "extraction" if call_id == 1 else "answer",
                 "method": "shared_extraction" if call_id == 1 else "abc"[call_id - 2],
                 "question_id": None if call_id == 1 else "Q1"}
        ledger.extend(({"event": "begin", **event},
                       {"event": "end", **event, "outcome": "response",
                        "input_tokens": 2, "output_tokens": 1}))
    (run / "calls.jsonl").write_text("\n".join(map(json.dumps, ledger)) + "\n", encoding="utf-8")
    _write_json(run / "extractions.json", {
        "fingerprint": "fixture", "records": [{"record_id": "R1", "text": "Service was slow."}],
        "extractions": [{"record_id": "R1", "status": "ok", "aspects": [{
            "category": "service", "sentiment": "negative", "evidence": ["Service was slow"]}]}],
        "provider_model": "fixture", "prompt_version": "v1", "schema_version": "v1",
        "coverage": {"total": 1, "success": 1, "failed_ids": []},
    })
    rows = [{"question_id": "Q1", "method": method, "requests": 1,
             "answer": {"method": method, "question_id": "Q1", "status": "ok",
                        "answer_text": "1", "numeric_claims": [{"metric": "negative_count",
                        "category": "service", "value": 1}], "usage": {"api_requests": 1}}}
            for method in "abc"]
    (run / "results.jsonl").write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")
    return {"plan_path": plan_path, "run_dir": run, "manifest_path": manifest,
            "csv_path": csv_path, "questions_path": questions, "references_path": refs,
            "dev_gold_path": gold}


def test_offline_score_checks_actual_rows_gold_and_ledger(tmp_path):
    paths = _fixture(tmp_path)
    report = score_pilot(**paths)
    assert report["status"] == "EXPLORATORY_DEV_SCORE"
    assert report["extraction"]["joint_micro_f1"] == 1
    assert {method: group["summary"]["per_type_success"]["count"]
            for method, group in report["methods"].items()} == dict.fromkeys("abc", 1)
    assert report["reference_review_complete"] is False
    assert report["formal_test_scored"] is False


def test_offline_score_rejects_changed_reference_and_duplicate_result(tmp_path):
    paths = _fixture(tmp_path)
    paths["references_path"].write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="source hash mismatch"):
        score_pilot(**paths)
    second = tmp_path / "second"
    second.mkdir()
    paths = _fixture(second)
    results = paths["run_dir"] / "results.jsonl"
    rows = results.read_text(encoding="utf-8").splitlines()
    results.write_text("\n".join([rows[0], rows[0], rows[2]]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing, duplicated or reordered"):
        score_pilot(**paths)


def test_ledger_rejects_unmatched_or_failed_call(tmp_path):
    path = tmp_path / "calls.jsonl"
    path.write_text(json.dumps({"event": "begin", "call_id": 1}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="length"):
        _checked_ledger(path, 1)
    path.write_text("\n".join(map(json.dumps, [
        {"event": "begin", "call_id": 1, "stage": "answer", "method": "a", "question_id": "Q1"},
        {"event": "end", "call_id": 1, "stage": "answer", "method": "a", "question_id": "Q1",
         "outcome": "error", "input_tokens": 1, "output_tokens": 1},
    ])), encoding="utf-8")
    with pytest.raises(ValueError, match="unmatched"):
        _checked_ledger(path, 1)


def test_offline_score_rejects_ledger_context_and_extraction_text_changes(tmp_path):
    paths = _fixture(tmp_path)
    calls = paths["run_dir"] / "calls.jsonl"
    events = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
    events[2]["method"] = events[3]["method"] = "c"
    calls.write_text("\n".join(map(json.dumps, events)) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="method/question counts"):
        score_pilot(**paths)
    events[2]["method"] = events[3]["method"] = "a"
    calls.write_text("\n".join(map(json.dumps, events)) + "\n", encoding="utf-8")
    extraction = paths["run_dir"] / "extractions.json"
    changed = json.loads(extraction.read_text(encoding="utf-8"))
    changed["records"][0]["text"] = "Service was slow. EXTRA"
    _write_json(extraction, changed)
    with pytest.raises(ValueError, match="extraction records"):
        score_pilot(**paths)
