from eval.questions import GoldReference
from scripts.compare_dev_pilots import error_types
from src.schemas import AnswerPayload


def test_error_taxonomy_distinguishes_rate_counts_and_denominator():
    reference = GoldReference(question_id="Q", task_type="rate", numerator=1,
                              denominator=4, rate=0.25, status="CANDIDATE_UNREVIEWED")
    answer = AnswerPayload(method="b", question_id="Q", status="ok",
                           answer_text="Zero of two service mentions were negative.",
                           numeric_claims=[{"metric": "negative_rate", "category": "service",
                                            "value": 0, "numerator": 0, "denominator": 2}],
                           denominator_explanation="Two service mentions.")
    assert error_types(answer, reference, {}) == [
        "rate_numerator_mismatch", "rate_denominator_mismatch", "rate_value_mismatch"]


def test_error_taxonomy_accepts_bounded_count_alias_and_flags_wrong_value():
    reference = GoldReference(question_id="Q", task_type="count", count=1,
                              status="CANDIDATE_UNREVIEWED")
    answer = AnswerPayload(method="a", question_id="Q", status="ok", answer_text="One.",
                           numeric_claims=[{"metric": "negative service reviews",
                                            "category": "service", "value": 1}])
    assert error_types(answer, reference, {}) == []
    wrong = answer.model_copy(deep=True)
    wrong.numeric_claims[0].value = 0
    assert error_types(wrong, reference, {}) == ["count_value_mismatch"]


def test_error_taxonomy_separates_comparison_and_citation_mismatches():
    reference = GoldReference(question_id="Q", task_type="evidence_explanation",
                              comparison_groups=[["food", "service"]],
                              category_counts={"food": 1, "service": 1},
                              source_record_ids=["R1"], status="CANDIDATE_UNREVIEWED")
    answer = AnswerPayload(method="c", question_id="Q", status="ok", answer_text="Food wins.",
                           comparison_groups=[["food"], ["service"]],
                           numeric_claims=[{"metric": "negative_count", "category": "food", "value": 2},
                                           {"metric": "negative_count", "category": "service", "value": 0}],
                           citations=[{"record_id": "R2", "quote": "slow service"}])
    assert error_types(answer, reference, {"R1": "slow service", "R2": "slow service"}) == [
        "comparison_groups_mismatch", "category_counts_mismatch",
        "candidate_evidence_id_or_quote_mismatch"]


def test_error_taxonomy_handles_selection_and_expected_refusal():
    selection = GoldReference(question_id="Q", task_type="selection",
                              selected_record_ids=["R1"], status="CANDIDATE_UNREVIEWED")
    answer = AnswerPayload(method="b", question_id="Q", status="ok", answer_text="None.")
    assert error_types(answer, selection, {}) == ["selection_set_mismatch"]
    missing = GoldReference(question_id="Q", task_type="insufficient_info",
                            insufficient_info=True, status="CANDIDATE_UNREVIEWED")
    assert error_types(answer, missing, {}) == ["missing_expected_refusal"]
