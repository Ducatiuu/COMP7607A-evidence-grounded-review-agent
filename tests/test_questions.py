import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval.questions import build_candidate_questions, build_gold_references
from src.semeval import CandidateSplit, GoldRecord


def _split():
    return CandidateSplit(seed=42, train_sha256="a" * 64, test_sha256="b" * 64,
                          train_source_url="synthetic://train", test_source_url="synthetic://test", dev_ids=["D1"],
                          test_ids=["R1", "R2", "R3", "R4"], packs=[["R1", "R2", "R3", "R4"]],
                          train_duplicate_groups=[], test_duplicate_groups=[], cross_split_train_ids=[],
                          conflict_excluded_train_ids=[], conflict_excluded_test_ids=[],
                          dev_label_counts={}, test_label_counts={}, manifest_sha256="c" * 64)


def _gold():
    return [
        GoldRecord(record_id="R1", aspects=[{"category": "food", "sentiment": "positive"}, {"category": "service", "sentiment": "negative"}]),
        GoldRecord(record_id="R2", aspects=[{"category": "service", "sentiment": "negative"}, {"category": "price", "sentiment": "negative"}]),
        GoldRecord(record_id="R3", aspects=[{"category": "food", "sentiment": "positive"}, {"category": "service", "sentiment": "positive"}]),
        GoldRecord(record_id="R4", aspects=[{"category": "food", "sentiment": "neutral"}]),
    ]


def test_six_candidates_per_pack_and_hand_calculated_gold_references():
    questions = build_candidate_questions(_split())
    references = build_gold_references(questions, _gold())
    assert [question.task_type for question in questions] == ["count", "rate", "selection", "comparison", "evidence_explanation", "insufficient_info"]
    assert all(question.status == "CANDIDATE_UNREVIEWED" for question in questions)
    assert len(references) == 6 and all(reference.status == "CANDIDATE_UNREVIEWED" for reference in references)
    assert references[0].count == 2
    assert (references[1].numerator, references[1].denominator, references[1].rate) == (2, 3, 2 / 3)
    assert references[2].selected_record_ids == ["R1"]
    assert [[category.value for category in group] for group in references[3].comparison_groups] == [["service"], ["food"]]
    assert {category.value: count for category, count in references[4].category_counts.items()} == {"food": 0, "service": 2, "price": 1}
    assert references[4].source_record_ids == ["R1", "R2"]
    assert references[5].insufficient_info is True


def test_undefined_rate_and_missing_gold_are_explicit():
    questions = build_candidate_questions(_split())
    gold = [GoldRecord(record_id=record_id, aspects=[{"category": "food", "sentiment": "positive"}]) for record_id in ["R1", "R2", "R3", "R4"]]
    references = build_gold_references(questions, gold)
    assert references[1].numerator == 0 and references[1].denominator == 0 and references[1].rate is None
    with pytest.raises(ValueError, match="missing or duplicate gold IDs"):
        build_gold_references(questions, gold[:-1])


def test_question_script_keeps_gold_separate_from_question_file(tmp_path):
    split_path, gold_path = tmp_path / "split.json", tmp_path / "gold.json"
    questions_path, references_path = tmp_path / "questions.json", tmp_path / "references.json"
    split_path.write_text(_split().model_dump_json(), encoding="utf-8")
    gold_path.write_text(json.dumps([item.model_dump(mode="json") for item in _gold()]), encoding="utf-8")
    completed = subprocess.run([sys.executable, "-m", "scripts.build_questions", "--split", str(split_path), "--gold", str(gold_path),
                                "--questions-out", str(questions_path), "--references-out", str(references_path)],
                               cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"status": "CANDIDATE_UNREVIEWED", "questions": 6, "references": 6}
    question_file = json.loads(questions_path.read_text(encoding="utf-8"))
    assert all("selected_record_ids" not in item and "source_record_ids" not in item for item in question_file)
    assert references_path.exists()
