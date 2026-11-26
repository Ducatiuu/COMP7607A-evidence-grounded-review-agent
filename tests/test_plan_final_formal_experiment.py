"""End-to-end final preflight on synthetic materials; no provider connection."""

import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from eval.question_audit import audit_candidate_questions
from eval.questions import GoldReference, QuestionCandidate
from scripts.plan_final_formal_experiment import PROMPT_SOURCES, build_final_plan
from scripts.run_formal_experiment import FormalInputs, checked_plan, run_formal
from scripts.score_formal_experiment import _confirmed_references, score_formal_run
from tests.test_run_formal_experiment import RuleClient
from tests.test_plan_formal_experiment import PACKS, ROOT, synthetic_sources


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def final_case(synthetic_sources, tmp_path):
    _, source_paths, source_lock, source_sheets = synthetic_sources
    root = tmp_path / "project"
    paths = {name: root / ("data/gold" if name in {"references", "test_gold"}
                          else "eval" if name == "metrics_code" else "data/processed") /
             ("metrics.py" if name == "metrics_code" else source.name)
             for name, source in source_paths.items()}
    for name, source in source_paths.items():
        paths[name].parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, paths[name])
    for relative in PROMPT_SOURCES.values():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    original = json.loads(source_lock.read_text(encoding="utf-8"))
    original["source_sha256"] = {name: _sha(path) for name, path in paths.items()}
    original_lock = root / "configs/formal_24_candidate.lock.json"
    _write(original_lock, original)
    reviews = []
    rows_by_slot = []
    for slot, source in ((1, source_sheets[0]), (2, source_sheets[1])):
        with source.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            row.update(reviewer_id=f"R{slot}", wording_ok="yes", answerability_ok="yes",
                       denominator_ok="yes", reference_ok="yes")
            if slot == 1 and row["question_id"] == "P11-Q6":
                row["wording_ok"] = "no"
                row["proposed_edit"] = "Define the rating threshold."
        path = root / f"outputs/reviews/reviewer_{slot}_questions_filled.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        reviews.append(path)
        rows_by_slot.append(rows)
    old_q = json.loads(paths["questions"].read_text(encoding="utf-8"))
    old_r = json.loads(paths["references"].read_text(encoding="utf-8"))
    new_q = json.loads(paths["questions"].read_text(encoding="utf-8"))
    wording = "Among reviews rated 2 stars or below, what fraction criticize service?"
    for question in new_q:
        if question["question_id"] == "P11-Q6":
            question["wording"] = wording
    selected_q = [QuestionCandidate.model_validate(q) for q in new_q if q["pack_id"] in PACKS]
    selected_ids = [q.question_id for q in selected_q]
    selected_r = [GoldReference.model_validate(r) for r in old_r if r["question_id"] in selected_ids]
    selected_audit = audit_candidate_questions(selected_q, selected_r, expected_packs=4)
    final_dir = root / "outputs/final"
    question_path = final_dir / "candidate_questions_120.json"
    selected_q_path = final_dir / "selected_questions_24.json"
    selected_r_path = final_dir / "selected_references_24.json"
    _write(question_path, new_q)
    _write(selected_q_path, [q.model_dump(mode="json") for q in selected_q])
    _write(selected_r_path, [r.model_dump(mode="json") for r in selected_r])
    old_p11 = next(q for q in old_q if q["question_id"] == "P11-Q6")
    old_ref = next(r for r in old_r if r["question_id"] == "P11-Q6")
    review_fields = ("wording_ok", "answerability_ok", "denominator_ok",
                     "reference_ok", "proposed_edit", "notes")
    queue = [{"question_id": "P11-Q6", "pack_id": "P11",
              "task_type": old_p11["task_type"], "wording": old_p11["wording"],
              "candidate_reference": GoldReference.model_validate(old_ref).model_dump(mode="json"),
              "reviewers": {f"R{slot}": {key: next(row for row in rows if row["question_id"] == "P11-Q6")[key]
                                           for key in review_fields}
                            for slot, rows in ((1, rows_by_slot[0]), (2, rows_by_slot[1]))},
              "final_decision": "revise_wording_rating_at_most_2",
              "decision_reason": "Owner confirmed the exact clearer wording and unchanged missing-info answer.",
              "adjudicator": "owner", "adjudicated_at": "2026-11-27",
              "final_question_wording": wording,
              "revised_question_confirmed": True, "final_reference_confirmed": True}]
    queue_path = root / "outputs/owner/queue.json"
    status_path = root / "outputs/owner/status.json"
    _write(queue_path, queue)
    _write(status_path, {"source_review_sheets_sha256": {reviews[0].name: _sha(reviews[0]),
                                                          reviews[1].name: _sha(reviews[1])},
                         "owner_queue_sha256": _sha(queue_path),
                         "resolved_question_ids": ["P11-Q6"]})
    rel = lambda path: path.relative_to(root).as_posix()
    source_hashes = {name: _sha(path) for name, path in paths.items()}
    source_hashes["questions"] = _sha(question_path)
    lock = {"schema_version": 2, "status": "OWNER_CONFIRMED_FINAL",
            "project_root_relative_to_lock": "../..",
            "original_lock_sha256": _sha(original_lock),
            "pack_ids": PACKS, "question_ids": selected_ids,
            "source_sha256": source_hashes,
            "reviewed_source_sha256": original["source_sha256"],
            "review_sheet_sha256": {"R1": _sha(reviews[0]), "R2": _sha(reviews[1])},
            "selected_questions_path": rel(selected_q_path),
            "selected_references_path": rel(selected_r_path),
            "selected_questions_file_sha256": _sha(selected_q_path),
            "selected_references_file_sha256": _sha(selected_r_path),
            "selected_questions_sha256": selected_audit["questions_sha256"],
            "selected_references_sha256": selected_audit["references_sha256"],
            "changed_question_ids": ["P11-Q6"], "changed_reference_ids": [],
            "adjudicated_question_ids": ["P11-Q6"],
            "owner_queue_path": rel(queue_path), "owner_status_path": rel(status_path),
            "owner_queue_sha256": _sha(queue_path), "owner_status_sha256": _sha(status_path),
            "scoring_rule_version": "strict", "prompt_versions": original["prompt_versions"],
            "prompt_source_sha256": {name: _sha(root / relative)
                                     for name, relative in PROMPT_SOURCES.items()}}
    lock_path = final_dir / "lock.json"
    _write(lock_path, lock)
    decision = {key: queue[0][key] for key in
                ("final_decision", "decision_reason", "adjudicator", "adjudicated_at",
                 "revised_question_confirmed", "final_reference_confirmed")}
    adj_path = final_dir / "adjudication.json"
    _write(adj_path, {"status": "HUMAN_ADJUDICATED", "adjudicator_id": "owner",
                      "resolved_question_ids": ["P11-Q6"], "decisions": {"P11-Q6": decision},
                      "review_sheet_sha256": lock["review_sheet_sha256"],
                      "owner_queue_sha256": _sha(queue_path),
                      "owner_status_sha256": _sha(status_path),
                      "selected_questions_sha256": lock["selected_questions_sha256"],
                      "selected_references_sha256": lock["selected_references_sha256"]})
    release_path = final_dir / "release.json"
    _write(release_path, {"status": "FROZEN", "signed_off_by": "owner",
                          "lock_sha256": _sha(lock_path), "pack_ids": PACKS,
                          "question_ids": selected_ids, "source_sha256": source_hashes,
                          "review_sheet_sha256": lock["review_sheet_sha256"],
                          "adjudication_sha256": _sha(adj_path),
                          "owner_queue_sha256": _sha(queue_path),
                          "owner_status_sha256": _sha(status_path),
                          "selected_questions_sha256": lock["selected_questions_sha256"],
                          "selected_references_sha256": lock["selected_references_sha256"],
                          "scoring_reference_status": "HUMAN_CONFIRMED",
                          "scoring_reference_sha256": _sha(selected_r_path),
                          "scoring_reference_question_ids": selected_ids,
                          "scoring_rule_version": "strict", "provider": "deepseek",
                          "model": "deepseek-flash", "prompt_versions": original["prompt_versions"],
                          "prompt_source_sha256": lock["prompt_source_sha256"]})
    kwargs = {"lock_path": lock_path, "split_path": paths["split"],
              "test_csv": paths["test_csv"], "dev_csv": paths["dev_csv"],
              "questions_path": question_path, "references_path": paths["references"],
              "test_gold_path": paths["test_gold"], "metrics_path": paths["metrics_code"],
              "reviewer_1_path": reviews[0], "reviewer_2_path": reviews[1],
              "adjudication_path": adj_path, "release_path": release_path,
              "run_dir": root / "outputs/run", "provider": "deepseek",
              "model": "deepseek-flash", "max_input_chars": 10000,
              "max_input_tokens": 8192, "max_output_tokens": 2048,
              "max_api_requests": 504, "max_cost_usd": "3.00",
              "input_usd_per_million": "0.3", "output_usd_per_million": "1.2",
              "price_source": "synthetic-test-assumption", "price_date": "2026-11-27",
              "timeout_seconds": 45}
    return kwargs, selected_r_path, queue_path


def test_final_revision_preflight_runner_and_scorer_share_one_frozen_version(final_case):
    kwargs, references_path, _ = final_case
    plan = build_final_plan(**kwargs)
    assert plan["material_state"] == "FROZEN" and plan["status"] == "FROZEN_PREFLIGHT_READY"
    assert plan["network_calls_made"] == 0 and not plan["execution_permitted"]
    plan_path = kwargs["lock_path"].parent / "plan.json"
    _write(plan_path, plan)
    inputs = FormalInputs(**{key: kwargs[key] for key in FormalInputs.__dataclass_fields__})
    assert checked_plan(plan_path, inputs) == plan
    questions = {item.question_id: item for item in
                 [QuestionCandidate.model_validate(q) for q in
                  json.loads(kwargs["questions_path"].read_text(encoding="utf-8"))]
                 if item.question_id in plan["question_ids"]}
    assert len(_confirmed_references(plan, inputs, references_path, questions)) == 24
    with pytest.raises(ValueError, match="explicit authorization"):
        run_formal(plan_path, inputs, client=None)
    mock_live = RuleClient()
    with pytest.raises(ValueError, match="pricing must be independently refreshed"):
        run_formal(plan_path, inputs, client=mock_live, authorized=True, mode="LIVE")
    assert not mock_live.requests
    assert not kwargs["run_dir"].exists()


def test_final_release_rejects_one_field_tampering_and_unconfirmed_revision(final_case):
    kwargs, _, queue_path = final_case
    assert build_final_plan(**kwargs)["material_state"] == "FROZEN"
    release = json.loads(kwargs["release_path"].read_text(encoding="utf-8"))
    release["selected_questions_sha256"] = "0" * 64
    _write(kwargs["release_path"], release)
    with pytest.raises(ValueError, match="freeze release"):
        build_final_plan(**kwargs)
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue[0]["revised_question_confirmed"] = False
    _write(queue_path, queue)
    with pytest.raises(ValueError, match="adjudication|hash"):
        build_final_plan(**kwargs)


def test_versioned_final_offline_batch_resume_and_score(final_case, monkeypatch):
    kwargs, references_path, _ = final_case
    plan = build_final_plan(**kwargs)
    plan_path = kwargs["lock_path"].parent / "plan.json"
    _write(plan_path, plan)
    inputs = FormalInputs(**{key: kwargs[key] for key in FormalInputs.__dataclass_fields__})
    first = RuleClient()
    paused = run_formal(plan_path, inputs, client=first, authorized=True, max_tasks=4)
    assert paused["status"] == "PAUSED" and paused["completed_method_answers"] == 3
    second = RuleClient()
    finished = run_formal(plan_path, inputs, client=second, authorized=True, resume=True)
    assert finished["status"] == "COMPLETE" and finished["completed_method_answers"] == 72
    assert len(list((kwargs["run_dir"] / "extractions").glob("*.json"))) == 4
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("offline scoring attempted network")))
    scored = score_formal_run(plan_path=plan_path, inputs=inputs,
                              run_dir=kwargs["run_dir"], final_references_path=references_path)
    assert scored["status"] == "SYNTHETIC_DIAGNOSTIC"
    assert len(scored["per_answer"]) == 72 and len(scored["paired_questions"]) == 24
    assert all(result["denominator"] == 24 for result in scored["methods"].values())


def test_versioned_final_uncertain_request_is_not_replayed(final_case):
    kwargs, _, _ = final_case
    plan_path = kwargs["lock_path"].parent / "plan.json"
    _write(plan_path, build_final_plan(**kwargs))
    inputs = FormalInputs(**{key: kwargs[key] for key in FormalInputs.__dataclass_fields__})
    first = RuleClient(fail_on_call=1)
    partial = run_formal(plan_path, inputs, client=first, authorized=True)
    assert partial["status"] == "PARTIAL" and partial["recorded_requests"] == 1
    resumed = RuleClient()
    with pytest.raises(ValueError, match="failed, duplicated|uncertain"):
        run_formal(plan_path, inputs, client=resumed, authorized=True, resume=True)
    assert not resumed.requests
