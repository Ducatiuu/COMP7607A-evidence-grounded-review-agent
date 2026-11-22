import json

from scripts.synthetic_protocol_smoke import main
from src.semeval import CandidateSplit


def test_full_synthetic_protocol_size_and_boundary_gate(tmp_path):
    assert main(["--out", str(tmp_path)]) == 0
    processed = tmp_path / "processed"
    split = CandidateSplit.model_validate_json((processed / "candidate_split.json").read_text(encoding="utf-8"))
    assert len(split.dev_ids) == 150 and len(split.test_ids) == 600
    assert len(split.packs) == 20 and all(len(pack) == 30 for pack in split.packs)
    questions = json.loads((processed / "candidate_questions.json").read_text(encoding="utf-8"))
    references = json.loads((tmp_path / "gold/candidate_references.json").read_text(encoding="utf-8"))
    assert len(questions) == len(references) == 120
    audit = json.loads((processed / "candidate_question_audit.json").read_text(encoding="utf-8"))
    assert audit["status"] == "CANDIDATE_REVIEW_REQUIRED" and not audit["coverage_gaps"]
    assert all(value > 0 for value in audit["boundary_examples"].values())
    subsets = json.loads((processed / "candidate_subsets.json").read_text(encoding="utf-8"))
    assert len(subsets["repeats"]) == 20 and len(subsets["gold_diagnostic"]) == len(subsets["evidence_review"]) == 30
    assert main(["--out", str(tmp_path)]) == 0
    repeated_split = CandidateSplit.model_validate_json((processed / "candidate_split.json").read_text(encoding="utf-8"))
    repeated_audit = json.loads((processed / "candidate_question_audit.json").read_text(encoding="utf-8"))
    assert repeated_split.manifest_sha256 == split.manifest_sha256
    assert repeated_audit["questions_sha256"] == audit["questions_sha256"]
