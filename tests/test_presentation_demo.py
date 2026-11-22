import json
from pathlib import Path

import pytest

from scripts.build_presentation_demo import build_entries, main
from src.absa_service import ExtractionService
from src.data_loader import dataset_fingerprint, load_csv
from src.demo_mock import PRESENTATION_FINGERPRINT, mock_for_demo
from src.schemas import Category, Sentiment


ROOT = Path(__file__).resolve().parents[1]


def test_simulated_fixture_is_deterministic_diverse_and_has_exact_spans(tmp_path):
    entries = build_entries()
    assert len(entries) == len({item["text"] for item in entries}) == 60
    assert {aspect["category"] for entry in entries for aspect in entry["aspects"]} == {item.value for item in Category}
    assert {aspect["sentiment"] for entry in entries for aspect in entry["aspects"]} == {item.value for item in Sentiment}
    assert all(aspect["evidence"][0] in entry["text"] for entry in entries for aspect in entry["aspects"])
    csv_path, annotation_path = tmp_path / "presentation.csv", tmp_path / "annotations.json"
    assert main(["--csv-out", str(csv_path), "--annotations-out", str(annotation_path)]) == 0
    assert json.loads(annotation_path.read_text(encoding="utf-8"))["records"] == entries
    records = load_csv(csv_path)
    assert dataset_fingerprint(records) == PRESENTATION_FINGERPRINT
    extracted = ExtractionService(mock_for_demo(records, method="extract"), provider_model="mock").extract(records)
    assert extracted.dataset.coverage.success == 60 and extracted.requests == 60
    altered = csv_path.read_text(encoding="utf-8").replace("noodles", "pasta", 1)
    csv_path.write_text(altered, encoding="utf-8")
    with pytest.raises(ValueError, match="only unchanged synthetic demo fixtures"):
        mock_for_demo(load_csv(csv_path), method="extract")
