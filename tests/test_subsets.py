import json

import pytest

from eval.questions import QuestionCandidate
from eval.subsets import CandidateSubsets, build_candidate_subsets
from scripts.build_subsets import main


TYPES = ["count", "rate", "selection", "comparison", "evidence_explanation", "insufficient_info"]


def questions():
    return [QuestionCandidate(question_id=f"P{pack:02d}-Q{index + 1}", pack_id=f"P{pack:02d}",
                              record_ids=[f"R{pack}"], task_type=task_type, wording="?", expected_fields=[])
            for pack in range(1, 21) for index, task_type in enumerate(TYPES)]


def test_subsets_cover_each_pack_without_results_and_have_hash(tmp_path):
    original = questions()
    path = tmp_path / "questions.json"
    target = tmp_path / "subsets.json"
    path.write_text(json.dumps([item.model_dump(mode="json") for item in original]), encoding="utf-8")
    assert main(["--questions", str(path), "--out", str(target)]) == 0
    result = CandidateSubsets.model_validate_json(target.read_text(encoding="utf-8"))
    assert len(result.repeats) == 20 and len(result.gold_diagnostic) == 30
    assert len(result.verification_ablation) == 30 and len(result.evidence_review) == 30
    for subset in (result.repeats, result.gold_diagnostic, result.evidence_review):
        assert len({item.split("-")[0] for item in subset}) == 20
    assert build_candidate_subsets(original) == result
    payload = result.model_dump()
    payload["manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        CandidateSubsets.model_validate(payload)
    with pytest.raises(ValueError, match="20 complete"):
        build_candidate_subsets(original[:-1])
