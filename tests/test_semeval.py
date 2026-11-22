import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.semeval import normalized_dedup_key, parse_restaurant_xml, prepare_candidate_split


def _xml(entries):
    body = []
    for record_id, text, category, polarity in entries:
        body.append(f'<sentence id="{record_id}"><text>{text}</text><aspectCategories><aspectCategory category="{category}" polarity="{polarity}"/></aspectCategories></sentence>')
    return "<sentences>" + "".join(body) + "</sentences>"


TRAIN = [
    ("T1", "Good food.", "food", "positive"),
    ("T2", "  good   FOOD. ", "food", "negative"),
    ("T3", "Bad service.", "service", "negative"),
    ("T4", "Shared text.", "food", "neutral"),
    ("T5", "High price.", "price", "negative"),
    ("T6", "Quiet room.", "ambience", "positive"),
]
TEST = [
    ("X1", "Shared text.", "food", "neutral"),
    ("X2", "Fresh meal.", "food", "positive"),
    ("X3", "Slow staff.", "service", "negative"),
    ("X4", "Cheap menu.", "price", "positive"),
    ("X5", "Warm lighting.", "ambience", "positive"),
]


def _corpora(tmp_path):
    train_path, test_path = tmp_path / "train.xml", tmp_path / "test.xml"
    train_path.write_text(_xml(TRAIN), encoding="utf-8")
    test_path.write_text(_xml(TEST), encoding="utf-8")
    train = parse_restaurant_xml(train_path, source_split="train", source_url="synthetic://train")
    test = parse_restaurant_xml(test_path, source_split="test", source_url="synthetic://test")
    return train_path, test_path, train, test


def test_xml_parse_preserves_text_and_gold_separately(tmp_path):
    _, _, train, _ = _corpora(tmp_path)
    assert len(train.records) == 6 and train.records[1].text == "  good   FOOD. "
    assert train.gold[1].aspects[0].sentiment.value == "negative"
    assert len(train.file_sha256) == 64 and train.source_url == "synthetic://train"
    assert normalized_dedup_key(train.records[0].text) == normalized_dedup_key(train.records[1].text)


def test_candidate_split_audits_conflict_and_cross_overlap(tmp_path):
    _, _, train, test = _corpora(tmp_path)
    one = prepare_candidate_split(train, test, seed=42, dev_size=2, test_size=4, pack_size=2)
    two = prepare_candidate_split(train, test, seed=42, dev_size=2, test_size=4, pack_size=2)
    assert one == two and one.status == "CANDIDATE_UNREVIEWED"
    assert one.train_duplicate_groups[0].record_ids == ["T1", "T2"]
    assert one.train_duplicate_groups[0].conflicting_labels is True
    assert one.cross_split_train_ids == ["T4"]
    assert "T1" not in one.dev_ids and "T2" not in one.dev_ids and "T4" not in one.dev_ids
    assert one.conflict_excluded_train_ids == ["T1", "T2"]
    assert one.train_source_url == "synthetic://train" and one.test_source_url == "synthetic://test"
    assert sum(one.test_label_counts.values()) == 4
    assert len(one.packs) == 2 and all(len(pack) == 2 for pack in one.packs)
    assert [record_id for pack in one.packs for record_id in pack] == one.test_ids


def test_xml_rejects_unsafe_and_inconsistent_content(tmp_path):
    path = tmp_path / "bad.xml"
    path.write_text('<!DOCTYPE foo [<!ENTITY x "secret">]><sentences><sentence id="a"><text>&x;</text></sentence></sentences>', encoding="utf-8")
    with pytest.raises(ValueError, match="DTD"):
        parse_restaurant_xml(path, source_split="train", source_url="synthetic://bad")
    path.write_text('<sentences><sentence id="a"><text>food</text><aspectCategories><aspectCategory category="food" polarity="positive"/><aspectCategory category="food" polarity="negative"/></aspectCategories></sentence></sentences>', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate gold category"):
        parse_restaurant_xml(path, source_split="train", source_url="synthetic://bad")
    path.write_text('<sentences><sentence id="a"><text>food</text><aspectCategories><aspectCategory category="unknown" polarity="positive"/></aspectCategories></sentence></sentences>', encoding="utf-8")
    with pytest.raises(ValueError):
        parse_restaurant_xml(path, source_split="train", source_url="synthetic://bad")


def test_prepare_script_outputs_run_csv_and_separate_gold(tmp_path):
    train_path, test_path, _, _ = _corpora(tmp_path)
    out, gold = tmp_path / "processed", tmp_path / "gold"
    command = [sys.executable, "-m", "scripts.prepare_semeval", "--train", str(train_path), "--test", str(test_path),
               "--train-source", "synthetic://train", "--test-source", "synthetic://test", "--out", str(out), "--gold-out", str(gold),
               "--dev-size", "2", "--test-size", "4", "--pack-size", "2"]
    completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((out / "candidate_split.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "CANDIDATE_UNREVIEWED"
    assert "sentiment" not in (out / "test.csv").read_text(encoding="utf-8")
    assert (gold / "test.json").exists()


def test_insufficient_records_or_bad_pack_size_is_explicit(tmp_path):
    _, _, train, test = _corpora(tmp_path)
    with pytest.raises(ValueError, match="insufficient distinct records"):
        prepare_candidate_split(train, test)
    with pytest.raises(ValueError, match="divisibility"):
        prepare_candidate_split(train, test, dev_size=2, test_size=3, pack_size=2)
