import json
from pathlib import Path

import pytest

from eval.run_challenge import main


ROOT = Path(__file__).resolve().parents[1]


def test_challenge_extracts_pair_and_never_claims_human_score(tmp_path):
    candidate = ROOT / "data/demo/challenge_candidate.json"
    output = tmp_path / "run"
    args = ["--candidate", str(candidate), "--out", str(output), "--mock"]
    assert main(args) == 0
    payload = json.loads((output / "predictions.json").read_text(encoding="utf-8"))
    assert payload["api_requests"] == 2 and payload["scores"] is None and payload["human_labels"] is None
    predictions = payload["predictions"]
    assert predictions[0]["aspects"][1]["sentiment"] == "negative"
    assert predictions[1]["aspects"][1]["sentiment"] == "positive"
    assert main(args) == 0
    altered = json.loads(candidate.read_text(encoding="utf-8"))
    altered["edited"]["text"] = "Different sentence."
    path = tmp_path / "altered.json"
    path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(ValueError, match="canned extraction fixture"):
        main(["--candidate", str(path), "--out", str(tmp_path / "other"), "--mock"])
    altered = json.loads(candidate.read_text(encoding="utf-8"))
    altered["candidate_edit_description"] = "changed"
    path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(ValueError, match="resume manifest mismatch"):
        main(["--candidate", str(path), "--out", str(output), "--mock"])
