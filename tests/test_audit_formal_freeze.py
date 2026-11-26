"""Synthetic-only checks for human-decision provenance and revision gates."""

from eval.questions import GoldReference, QuestionCandidate
from scripts.audit_formal_freeze import assess_decisions


def _question(wording: str) -> QuestionCandidate:
    return QuestionCandidate(question_id="P01-Q2", pack_id="P01", record_ids=["R1"],
                             task_type="rate", wording=wording,
                             expected_fields=["numerator", "denominator", "rate"],
                             denominator_spec="aspect_mentions", rate_category="price")


def _reference() -> GoldReference:
    return GoldReference(question_id="P01-Q2", task_type="rate",
                         numerator=0, denominator=0, rate=None)


def test_owner_retains_zero_denominator_candidate_without_using_exploratory_revision():
    original = _question("Price question")
    reference = _reference()
    queue = [{"question_id": "P01-Q2", "final_decision": "retain_price_undefined_rate",
              "decision_reason": "Human confirms undefined rate as the intended answer.",
              "adjudicator": "owner", "adjudicated_at": "2026-11-27"}]
    assert assess_decisions(queue, {"P01-Q2"}, {"P01-Q2": original},
                            {"P01-Q2": reference}, {"P01-Q2": original},
                            {"P01-Q2": reference}) == []
    changed = original.model_copy(update={"wording": "Food question"})
    blockers = assess_decisions(queue, {"P01-Q2"}, {"P01-Q2": original},
                                {"P01-Q2": reference}, {"P01-Q2": changed},
                                {"P01-Q2": reference})
    assert any("retained question/reference differs" in item for item in blockers)


def test_missing_decision_and_unconfirmed_revision_block_freeze():
    original = _question("Original wording")
    revised = original.model_copy(update={"wording": "Revised wording"})
    reference = _reference()
    base = {"question_id": "P01-Q2", "final_decision": "revise_wording",
            "decision_reason": "Human requested a clearer threshold.",
            "adjudicator": "owner", "adjudicated_at": "2026-11-27",
            "final_question_wording": "Revised wording"}
    inputs = ({"P01-Q2": original}, {"P01-Q2": reference},
              {"P01-Q2": revised}, {"P01-Q2": reference})
    blockers = assess_decisions([base], {"P01-Q2"}, *inputs)
    assert blockers == ["P01-Q2: revised question has no final human confirmation"]
    approved = dict(base, revised_question_confirmed=True)
    assert assess_decisions([approved], {"P01-Q2"}, *inputs) == []
    missing = dict(base, decision_reason=None)
    assert "human adjudication is incomplete" in assess_decisions(
        [missing], {"P01-Q2"}, *inputs)[0]
    wrong_wording = dict(approved, final_question_wording="Other wording")
    assert any("does not match the owner decision" in item for item in
               assess_decisions([wrong_wording], {"P01-Q2"}, *inputs))


def test_unadjudicated_change_and_duplicate_decisions_are_rejected():
    original = _question("Original wording")
    changed = original.model_copy(update={"wording": "Unapproved change"})
    reference = _reference()
    blockers = assess_decisions([], set(), {"P01-Q2": original},
                                {"P01-Q2": reference}, {"P01-Q2": changed},
                                {"P01-Q2": reference})
    assert blockers == ["P01-Q2: unadjudicated question/reference was changed"]
    duplicate = [{"question_id": "P01-Q2"}, {"question_id": "P01-Q2"}]
    blockers = assess_decisions(duplicate, {"P01-Q2"}, {"P01-Q2": original},
                                {"P01-Q2": reference}, {"P01-Q2": original},
                                {"P01-Q2": reference})
    assert any("does not cover exactly" in item for item in blockers)
