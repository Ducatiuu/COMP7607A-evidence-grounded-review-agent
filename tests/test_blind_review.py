import csv

import pytest

from eval.blind_review import export_blind_review
from eval.run_method import main as run_method_main


def test_blind_export_separates_method_mapping_and_leaves_labels_blank(tmp_path):
    runs = []
    for method in "abc":
        directory = tmp_path / method
        assert run_method_main(["--method", method, "--mock", "--out", str(directory)]) == 0
        runs.append(directory)
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
