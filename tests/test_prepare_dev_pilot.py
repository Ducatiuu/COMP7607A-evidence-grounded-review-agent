import csv
import json

import pytest

from scripts.prepare_dev_pilot import main
from src.semeval import CandidateSplit, GoldRecord


def _sources(tmp_path, *, reverse_dev=False):
    dev_ids = [f"D{number:03d}" for number in range(35)]
    test_ids = [f"T{number:03d}" for number in range(30)]
    split = CandidateSplit(
        seed=42, train_sha256="a" * 64, test_sha256="b" * 64,
        train_source_url="synthetic://train", test_source_url="synthetic://test",
        dev_ids=dev_ids, test_ids=test_ids, packs=[test_ids],
        train_duplicate_groups=[], test_duplicate_groups=[], cross_split_train_ids=[],
        conflict_excluded_train_ids=[], conflict_excluded_test_ids=[],
        dev_label_counts={}, test_label_counts={}, manifest_sha256="c" * 64,
    )
    split_path, dev_path, gold_path = (tmp_path / name for name in ("split.json", "dev.csv", "gold.json"))
    split_path.write_text(split.model_dump_json(), encoding="utf-8")
    with dev_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["record_id", "text"])
        writer.writeheader()
        for record_id in reversed(dev_ids) if reverse_dev else dev_ids:
            writer.writerow({"record_id": record_id, "text": f"Review {record_id} with food and service."})
    gold = [GoldRecord(record_id=record_id, aspects=[
        {"category": "food", "sentiment": "positive"},
        {"category": "service", "sentiment": "negative" if number % 2 else "positive"},
    ]) for number, record_id in enumerate(dev_ids)]
    gold_path.write_text(json.dumps([item.model_dump(mode="json") for item in gold]), encoding="utf-8")
    return split_path, dev_path, gold_path


def _args(tmp_path, sources):
    split_path, dev_path, gold_path = sources
    return ["--split", str(split_path), "--dev", str(dev_path), "--dev-gold", str(gold_path),
            "--out-dir", str(tmp_path / "pilot"),
            "--references-out", str(tmp_path / "gold" / "references.json")]


def test_pilot_is_deterministic_dev_only_and_keeps_references_separate(tmp_path, capsys):
    args = _args(tmp_path, _sources(tmp_path))
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert (result["status"], result["records"], result["questions"]) == (
        "DEV_PILOT_CANDIDATE_UNREVIEWED", 30, 10)
    manifest = json.loads((tmp_path / "pilot" / "manifest.json").read_text(encoding="utf-8"))
    questions = json.loads((tmp_path / "pilot" / "questions.json").read_text(encoding="utf-8"))
    references = json.loads((tmp_path / "gold" / "references.json").read_text(encoding="utf-8"))
    with (tmp_path / "pilot" / "pilot.csv").open(encoding="utf-8", newline="") as stream:
        pilot_rows = list(csv.DictReader(stream))
    ids = [row["record_id"] for row in pilot_rows]
    assert ids == manifest["record_ids"] and len(ids) == len(set(ids)) == 30
    assert all(item["record_ids"] == ids and item["status"] == "CANDIDATE_UNREVIEWED" for item in questions)
    assert [item["question_id"] for item in questions] == [item["question_id"] for item in references]
    assert {item["task_type"] for item in questions} == {
        "count", "rate", "selection", "comparison", "evidence_explanation", "insufficient_info"}
    assert references[0]["count"] == references[1]["count"]
    assert references[2]["rate"] == references[3]["rate"]
    assert references[4]["selected_record_ids"] == references[5]["selected_record_ids"]
    assert references[6]["comparison_groups"] == references[7]["comparison_groups"]
    assert not manifest["human_review_complete"]
    assert "T000" not in json.dumps(questions) and "T000" not in json.dumps(pilot_rows)
    assert "count" not in questions[0] and "source_record_ids" not in questions[0]
    original_manifest = (tmp_path / "pilot" / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        main(args)
    assert (tmp_path / "pilot" / "manifest.json").read_bytes() == original_manifest


def test_pilot_rejects_misaligned_dev_before_writing(tmp_path):
    args = _args(tmp_path, _sources(tmp_path, reverse_dev=True))
    with pytest.raises(ValueError, match="dev CSV must align"):
        main(args)
    assert not (tmp_path / "pilot").exists()
    assert not (tmp_path / "gold").exists()
