import csv
import json

import pytest

from eval.blind_review import export_blind_review
from eval.run_method import main as run_method_main


def _mock_runs(tmp_path):
    runs = []
    for method in "abc":
        directory = tmp_path / method
        assert run_method_main(["--method", method, "--mock", "--out", str(directory)]) == 0
        runs.append(directory)
    return runs


def test_blind_export_separates_method_mapping_and_leaves_labels_blank(tmp_path):
    runs = _mock_runs(tmp_path)
    output = tmp_path / "review"
    result = export_blind_review(runs, ["demo-rate"], output)
    assert result["review_items"] == 3 and result["labels_written"] == 0
    with (output / "review_items.csv").open(encoding="utf-8", newline="") as stream:
        review = list(csv.DictReader(stream))
    with (output / "private_mapping.csv").open(encoding="utf-8", newline="") as stream:
        mapping = list(csv.DictReader(stream))
    assert len(review) == len(mapping) == 3
    assert "method" not in review[0] and {row["method"] for row in mapping} == set("abc")
    assert {row["blind_answer_id"] for row in review} == {row["blind_answer_id"] for row in mapping}
    with pytest.raises(ValueError, match="already exists"):
        export_blind_review(runs, ["demo-rate"], output)


@pytest.mark.parametrize("leak", ["As Method C, I calculated this.",
                                           "The dynamic agent selected a tool.",
                                           "I called aggregate_aspects to answer."])
def test_blind_export_blocks_explicit_method_identity_before_writing(tmp_path, leak):
    runs = _mock_runs(tmp_path)
    path = runs[2] / "answers.jsonl"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["answer"]["answer_text"] = leak
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    output = tmp_path / "review"
    with pytest.raises(ValueError, match="self-identifying"):
        export_blind_review(runs, ["demo-rate"], output)
    assert not (output / "review_items.csv").exists()
    assert not (output / "private_mapping.csv").exists()


def test_blind_export_rejects_mismatched_tasks_and_duplicate_attempts(tmp_path):
    runs = _mock_runs(tmp_path)
    manifest_path = runs[2] / "manifest.json"
    original_manifest = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(original_manifest)
    manifest["tasks_sha256"] = "f" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="paired run configuration"):
        export_blind_review(runs, ["demo-rate"], tmp_path / "review")

    manifest_path.write_text(original_manifest, encoding="utf-8")
    manifest = json.loads(original_manifest)
    manifest["task_keys"] = ['["other",0]']
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="paired run configuration"):
        export_blind_review(runs, ["demo-rate"], tmp_path / "review")

    manifest_path.write_text(original_manifest, encoding="utf-8")
    row_path = runs[0] / "answers.jsonl"
    row = row_path.read_text(encoding="utf-8")
    row_path.write_text(row + row, encoding="utf-8")
    with pytest.raises(ValueError, match="nonconsecutive attempts"):
        export_blind_review(runs, ["demo-rate"], tmp_path / "review")


def test_blind_export_allows_unrelated_grade_a_text(tmp_path):
    runs = _mock_runs(tmp_path)
    path = runs[0] / "answers.jsonl"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["answer"]["answer_text"] = "The restaurant received a grade A for cleanliness."
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert export_blind_review(runs, ["demo-rate"], tmp_path / "review")["review_items"] == 3


def test_blind_export_checks_visible_citation_quote(tmp_path):
    runs = _mock_runs(tmp_path)
    path = runs[1] / "answers.jsonl"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["answer"]["citations"] = [{"record_id": "R01", "quote": "Method B used a fixed workflow."}]
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="self-identifying"):
        export_blind_review(runs, ["demo-rate"], tmp_path / "review")
