import json

import pytest

from eval.question_audit import audit_candidate_questions
from eval.questions import build_candidate_questions, build_gold_references
from scripts.audit_questions import main
from src.semeval import CandidateSplit, GoldRecord


def _fixture():
    split = CandidateSplit(seed=42, train_sha256="a" * 64, test_sha256="b" * 64,
                           train_source_url="synthetic://train", test_source_url="synthetic://test", dev_ids=["D1"],
                           test_ids=["R1", "R2", "R3"], packs=[["R1"], ["R2"], ["R3"]],
                           train_duplicate_groups=[], test_duplicate_groups=[], cross_split_train_ids=[],
                           conflict_excluded_train_ids=[], conflict_excluded_test_ids=[],
                           dev_label_counts={}, test_label_counts={}, manifest_sha256="c" * 64)
    gold = [GoldRecord(record_id="R1", aspects=[{"category": "food", "sentiment": "positive"},
                                               {"category": "service", "sentiment": "negative"}]),
            GoldRecord(record_id="R2", aspects=[{"category": "food", "sentiment": "positive"}]),
            GoldRecord(record_id="R3", aspects=[{"category": "food", "sentiment": "positive"}])]
    return split, gold


def test_audit_checks_boundary_and_metadata_coverage_without_freezing(tmp_path):
    split, gold = _fixture()
    questions = build_candidate_questions(split)
    references = build_gold_references(questions, gold)
    audit = audit_candidate_questions(questions, references, expected_packs=3, expected_pack_size=1)
    assert audit["status"] == "CANDIDATE_REVIEW_REQUIRED" and audit["human_review_complete"] is False
    assert audit["boundary_examples"] == {"empty_selection": 2, "nonempty_selection": 1,
                                           "undefined_rate": 2, "comparison_tie": 4}
    assert audit["missing_metadata_variants"] == ["customer_id", "date", "rating"]
    question_path, reference_path, output = (tmp_path / name for name in ["questions.json", "refs.json", "audit.json"])
    question_path.write_text(json.dumps([item.model_dump(mode="json") for item in questions]), encoding="utf-8")
    reference_path.write_text(json.dumps([item.model_dump(mode="json") for item in references]), encoding="utf-8")
    assert main(["--questions", str(question_path), "--references", str(reference_path),
                 "--out", str(output), "--expected-packs", "3", "--expected-pack-size", "1"]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["questions_sha256"] == audit["questions_sha256"]
    without_nonempty = [GoldRecord(record_id=record.record_id, aspects=[item for item in record.aspects if item.category.value != "service"])
                        for record in gold]
    lacking = audit_candidate_questions(questions, build_gold_references(questions, without_nonempty),
                                        expected_packs=3, expected_pack_size=1)
    assert lacking["status"] == "NEEDS_REVISION" and "nonempty_selection" in lacking["coverage_gaps"]
    misaligned = list(questions)
    misaligned[7] = misaligned[7].model_copy(update={"record_ids": ["R1"]})
    scope_audit = audit_candidate_questions(misaligned, references, expected_packs=3, expected_pack_size=1)
    assert "pack_scope_alignment" in scope_audit["coverage_gaps"]
    with pytest.raises(ValueError, match="IDs must align"):
        audit_candidate_questions(questions, references[:-1], expected_packs=3, expected_pack_size=1)
