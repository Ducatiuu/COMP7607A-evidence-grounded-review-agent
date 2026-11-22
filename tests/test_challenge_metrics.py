import json

import pytest
from pydantic import ValidationError

from eval.challenge import run_synthetic_challenge
from eval.challenge_metrics import ChallengePrediction, ChallengeReference, prediction_from_run_payload, score_challenge_predictions
from scripts.score_challenge import main as score_main


def _reference():
    return ChallengeReference(
        pair_id="synthetic-pair-01", source_gold={"record_id": "CH01-A", "aspects": [
            {"category": "food", "sentiment": "positive"}, {"category": "service", "sentiment": "negative"}]},
        edited_gold={"record_id": "CH01-B", "aspects": [
            {"category": "food", "sentiment": "positive"}, {"category": "service", "sentiment": "positive"}]},
        intended_change_categories=["service"], stable_categories=["food"], subgroup_tags=["contrast"],
        provenance="SYNTHETIC_TEST_ONLY",
    )


def test_challenge_score_is_separate_and_preserves_failures(tmp_path):
    run_dir = tmp_path / "run"
    run_synthetic_challenge("data/demo/challenge_candidate.json", run_dir)
    payload_path = run_dir / "predictions.json"
    prediction = prediction_from_run_payload(json.loads(payload_path.read_text(encoding="utf-8")))
    reference = _reference()
    result = score_challenge_predictions([prediction], [reference])
    assert result["provenance"] == "SYNTHETIC_TEST_ONLY" and result["pair_count"] == 1
    assert result["intended_change"] == {"correct": 1, "total": 1, "accuracy": 1}
    assert result["stable_aspects"]["accuracy"] == 1 and result["by_subgroup"]["contrast"]["support_pairs"] == 1
    references_path = tmp_path / "references.json"
    output = tmp_path / "score.json"
    references_path.write_text(json.dumps([reference.model_dump(mode="json")]), encoding="utf-8")
    assert score_main(["--predictions", str(payload_path), "--references", str(references_path), "--out", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["pair_accuracy"] == 1

    wrong = prediction.model_dump(mode="json")
    wrong["edited"]["aspects"][1]["sentiment"] = "negative"
    wrong_result = score_challenge_predictions([ChallengePrediction.model_validate(wrong)], [reference])
    assert wrong_result["intended_change"]["accuracy"] == 0
    assert wrong_result["stable_aspects"]["accuracy"] == 1 and wrong_result["pair_accuracy"] == 0
    wrong["edited"] = {"record_id": "CH01-B", "aspects": [], "status": "failed", "error": "timeout"}
    failure = score_challenge_predictions([ChallengePrediction.model_validate(wrong)], [reference])
    assert failure["failed_extraction_pairs"] == 1 and failure["stable_aspects"]["accuracy"] == 0


def test_human_provenance_cannot_be_claimed_by_mock_or_missing_reviewers():
    reference = _reference()
    base = reference.model_dump(mode="json")
    with pytest.raises(ValidationError, match="subgroup tags"):
        ChallengeReference.model_validate({**base, "subgroup_tags": []})
    base["provenance"] = "HUMAN_ADJUDICATED"
    with pytest.raises(ValidationError, match="two independent reviewers"):
        ChallengeReference.model_validate(base)
    base.update(independent_reviewer_ids=["reviewer-a", "reviewer-b"], adjudicator_id="reviewer-c",
                annotation_record_sha256="a" * 64)
    human = ChallengeReference.model_validate(base)
    mock = ChallengePrediction(pair_id=reference.pair_id,
                               source={"record_id": "CH01-A", "aspects": [], "status": "ok"},
                               edited={"record_id": "CH01-B", "aspects": [], "status": "ok"}, mode="MOCK")
    with pytest.raises(ValueError, match="MOCK predictions"):
        score_challenge_predictions([mock], [human])
    with pytest.raises(ValueError, match="pair IDs"):
        score_challenge_predictions([mock, mock], [reference])
