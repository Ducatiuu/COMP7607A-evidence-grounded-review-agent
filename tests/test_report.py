import json
from pathlib import Path

import pytest

from eval.questions import GoldReference
from eval.report import summarize_runs
from eval.run_method import main as run_method_main
from scripts.summarize_runs import main as summarize_main


ROOT = Path(__file__).resolve().parents[1]


def test_report_scores_actual_mock_rows_and_pairs_methods(tmp_path):
    dirs = []
    for method, condition in [("a", "main"), ("b", "main"), ("c", "main"), ("c", "ablation"), ("c", "repeats")]:
        directory = tmp_path / f"{method}-{condition}"
        assert run_method_main(["--method", method, "--condition", condition, "--mock", "--out", str(directory)]) == 0
        dirs.append(directory)
    target = tmp_path / "report.json"
    assert summarize_main(["--runs", *(str(item) for item in dirs), "--references",
                           str(ROOT / "data/demo/core_reference.json"), "--out", str(target)]) == 0
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["mode"] == "MOCK_ONLY_NOT_RESEARCH_RESULT"
    assert report["paired"]["main"]["count"] == 1
    assert report["paired"]["main_vs_ablation_c"]["count"] == 1
    assert report["repeat_variability"]["c"] == {"complete_question_pairs": 1, "status_disagreement_count": 0,
                                                  "primary_success_disagreement_count": 0, "incomplete_question_pairs": 0}
    assert all(item["scores"]["equal_type_average"] == 1 for item in report["runs"])
    assert all(item["cost_usd"] is None for item in report["runs"])
    refs = [GoldReference.model_validate(item) for item in json.loads((ROOT / "data/demo/core_reference.json").read_text(encoding="utf-8"))]
    with pytest.raises(ValueError, match="duplicate condition"):
        summarize_runs([dirs[0], dirs[0]], refs)
    row_path = dirs[0] / "answers.jsonl"
    row = json.loads(row_path.read_text(encoding="utf-8"))
    row["question_id"] = "unknown"
    row_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        summarize_runs(dirs, refs)
