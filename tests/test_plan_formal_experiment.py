"""Formal preflight tests use synthetic SemEval-shaped records only."""

import csv
import hashlib
import json
from pathlib import Path

import pytest

from eval.question_audit import audit_candidate_questions
from eval.questions import GoldReference, QuestionCandidate
from scripts.export_question_review import _FIELDS
from scripts.plan_formal_experiment import build_plan, require_formal_execution_ready
from scripts.synthetic_protocol_smoke import main as synthetic_main
from src.live_cost import BudgetError


PACKS = ["P01", "P06", "P11", "P16"]
ROOT = Path(__file__).resolve().parents[1]


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def synthetic_sources(tmp_path_factory):
    root = tmp_path_factory.mktemp("formal-preflight")
    assert synthetic_main(["--out", str(root)]) == 0
    processed, gold = root / "processed", root / "gold"
    paths = {
        "split": processed / "candidate_split.json",
        "test_csv": processed / "test.csv", "dev_csv": processed / "dev.csv",
        "questions": processed / "candidate_questions.json",
        "references": gold / "candidate_references.json",
        "test_gold": gold / "test.json", "metrics_code": ROOT / "eval/metrics.py",
    }
    questions = [QuestionCandidate.model_validate(x) for x in
                 json.loads(paths["questions"].read_text(encoding="utf-8"))]
    references = [GoldReference.model_validate(x) for x in
                  json.loads(paths["references"].read_text(encoding="utf-8"))]
    selected = [q for q in questions if q.pack_id in PACKS]
    selected_ids = {q.question_id for q in selected}
    selected_refs = [r for r in references if r.question_id in selected_ids]
    audit = audit_candidate_questions(selected, selected_refs, expected_packs=4)
    lock = {
        "status": "CANDIDATE_UNREVIEWED", "pack_ids": PACKS,
        "question_ids": [q.question_id for q in selected],
        "source_sha256": {name: _sha(path) for name, path in paths.items()},
        "selected_questions_sha256": audit["questions_sha256"],
        "selected_references_sha256": audit["references_sha256"],
        "scoring_rule_version": "strict",
        "prompt_versions": {"extraction": "extract-v2", "query": "query-v4",
                            "answer": "answer-v6", "decision": "decision-v5",
                            "direct": "direct-v3"},
    }
    lock_path = root / "lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    by_id = {r.question_id: r for r in selected_refs}
    sheets = []
    for slot in (1, 2):
        path = root / f"reviewer_{slot}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=_FIELDS)
            writer.writeheader()
            for question in selected:
                row = dict.fromkeys(_FIELDS, "")
                row.update(question_id=question.question_id, pack_id=question.pack_id,
                           task_type=question.task_type, wording=question.wording,
                           record_ids=json.dumps(question.record_ids),
                           expected_fields=json.dumps(question.expected_fields),
                           denominator_spec=question.denominator_spec or "",
                           rate_category=question.rate_category.value if question.rate_category else "",
                           reference_json=by_id[question.question_id].model_dump_json(),
                           questions_sha256=audit["questions_sha256"],
                           references_sha256=audit["references_sha256"])
                writer.writerow(row)
        sheets.append(path)
    return root, paths, lock_path, sheets


def _arguments(sources, tmp_path):
    _, paths, lock_path, sheets = sources
    return dict(lock_path=lock_path, split_path=paths["split"],
                test_csv=paths["test_csv"], dev_csv=paths["dev_csv"],
                questions_path=paths["questions"], references_path=paths["references"],
                test_gold_path=paths["test_gold"], metrics_path=paths["metrics_code"],
                reviewer_1_path=sheets[0], reviewer_2_path=sheets[1],
                run_dir=tmp_path / "unrun", provider="deepseek", model="deepseek-flash",
                max_input_chars=10000, max_input_tokens=8192, max_output_tokens=2048,
                max_api_requests=504, max_cost_usd="3.00",
                input_usd_per_million="0.3", output_usd_per_million="1.2",
                price_source="synthetic-test-assumption", price_date="2026-11-24",
                timeout_seconds=45)


def test_candidate_preflight_is_read_only_and_execution_closed(synthetic_sources, tmp_path):
    args = _arguments(synthetic_sources, tmp_path)
    plan = build_plan(**args)
    assert plan["question_count"] == 24 and plan["record_count"] == 120
    assert plan["max_api_requests"] == 504 and plan["network_calls_made"] == 0
    assert plan["material_state"] == "CANDIDATE_UNFROZEN"
    assert plan["question_review_state"] == "PENDING_HUMAN_REVIEW"
    assert not plan["execution_permitted"] and not args["run_dir"].exists()
    with pytest.raises(ValueError, match="completed review"):
        require_formal_execution_ready(plan)


def test_wrong_pack_and_duplicate_question_rejected(synthetic_sources, tmp_path):
    args = _arguments(synthetic_sources, tmp_path)
    lock = json.loads(args["lock_path"].read_text(encoding="utf-8"))
    lock["pack_ids"][-1] = "P17"
    wrong = tmp_path / "wrong_lock.json"
    wrong.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate lock"):
        build_plan(**{**args, "lock_path": wrong})
    questions = json.loads(args["questions_path"].read_text(encoding="utf-8"))
    questions[1]["question_id"] = questions[0]["question_id"]
    duplicate = tmp_path / "duplicate_questions.json"
    duplicate.write_text(json.dumps(questions), encoding="utf-8")
    lock["pack_ids"] = PACKS
    lock["source_sha256"]["questions"] = _sha(duplicate)
    duplicate_lock = tmp_path / "duplicate_lock.json"
    duplicate_lock.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(ValueError, match="repeated"):
        build_plan(**{**args, "lock_path": duplicate_lock,
                      "questions_path": duplicate})


def test_hash_mismatch_unfrozen_release_and_missing_budget_rejected(synthetic_sources, tmp_path):
    args = _arguments(synthetic_sources, tmp_path)
    mutated = tmp_path / "changed_test.csv"
    mutated.write_bytes(args["test_csv"].read_bytes() + b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        build_plan(**{**args, "test_csv": mutated})
    release = tmp_path / "fake_release.json"
    adjudication = tmp_path / "fake_adjudication.json"
    release.write_text('{"status":"FROZEN"}', encoding="utf-8")
    adjudication.write_text('{"status":"HUMAN_ADJUDICATED"}', encoding="utf-8")
    with pytest.raises(ValueError, match="review is incomplete"):
        build_plan(**{**args, "release_path": release,
                      "adjudication_path": adjudication})
    with pytest.raises(ValueError, match="cost cap"):
        build_plan(**{**args, "max_cost_usd": ""})
    with pytest.raises(BudgetError, match="worst case"):
        build_plan(**{**args, "max_cost_usd": "0.01"})


def test_reviewer_question_or_reference_tampering_rejected(synthetic_sources, tmp_path):
    args = _arguments(synthetic_sources, tmp_path)
    with args["reviewer_1_path"].open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["question_id"] = "P01-UNKNOWN"
    altered = tmp_path / "altered.csv"
    with altered.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="immutable"):
        build_plan(**{**args, "reviewer_1_path": altered})
    rows[0]["question_id"] = "P01-Q1"
    rows[0]["reference_json"] = '{"count":999}'
    with altered.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="independent reference"):
        build_plan(**{**args, "reviewer_1_path": altered})


def test_completed_reviews_and_hashed_freeze_are_distinct_from_candidate(synthetic_sources, tmp_path):
    args = _arguments(synthetic_sources, tmp_path)
    filled = []
    for slot in (1, 2):
        with args[f"reviewer_{slot}_path"].open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            row["reviewer_id"] = f"R{slot}"
            for field in ("wording_ok", "answerability_ok", "denominator_ok", "reference_ok"):
                row[field] = "yes"
        path = tmp_path / f"filled_{slot}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        filled.append(path)
    adjudication = tmp_path / "adjudication.json"
    adjudication.write_text(json.dumps({"status": "HUMAN_ADJUDICATED",
                                        "adjudicator_id": "R3",
                                        "resolved_question_ids": []}), encoding="utf-8")
    lock = json.loads(args["lock_path"].read_text(encoding="utf-8"))
    release = tmp_path / "release.json"
    release.write_text(json.dumps({
        "status": "FROZEN", "signed_off_by": "maintainer",
        "pack_ids": PACKS, "question_ids": lock["question_ids"],
        "source_sha256": lock["source_sha256"],
        "review_sheet_sha256": {"R1": _sha(filled[0]), "R2": _sha(filled[1])},
        "adjudication_sha256": _sha(adjudication),
        "scoring_rule_version": "strict",
    }), encoding="utf-8")
    plan = build_plan(**{**args, "reviewer_1_path": filled[0],
                         "reviewer_2_path": filled[1], "adjudication_path": adjudication,
                         "release_path": release})
    assert plan["status"] == "FROZEN_PREFLIGHT_READY"
    assert plan["material_state"] == "FROZEN" and plan["material_gate_passed"]
    assert not plan["execution_permitted"]
    with pytest.raises(ValueError, match="runner has not been implemented"):
        require_formal_execution_ready(plan)
    bad_release = json.loads(release.read_text(encoding="utf-8"))
    bad_release["review_sheet_sha256"]["R1"] = "0" * 64
    release.write_text(json.dumps(bad_release), encoding="utf-8")
    with pytest.raises(ValueError, match="freeze record"):
        build_plan(**{**args, "reviewer_1_path": filled[0],
                      "reviewer_2_path": filled[1], "adjudication_path": adjudication,
                      "release_path": release})
