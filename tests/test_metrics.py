import pytest

from eval.metrics import ConditionedPrediction, absa_scores, conditioned_sentiment_scores, score_answer, summarize_question_scores
from eval.questions import GoldReference
from src.schemas import AnswerPayload
from src.semeval import GoldRecord
from test_tools import _dataset


def _gold():
    return [
        GoldRecord(record_id="R01", aspects=[{"category": "food", "sentiment": "positive"}, {"category": "service", "sentiment": "negative"}]),
        GoldRecord(record_id="R02", aspects=[{"category": "service", "sentiment": "negative"}, {"category": "price", "sentiment": "negative"}]),
        GoldRecord(record_id="R03", aspects=[{"category": "service", "sentiment": "positive"}, {"category": "food", "sentiment": "positive"}]),
        GoldRecord(record_id="R04", aspects=[{"category": "food", "sentiment": "neutral"}]),
    ]


def test_absa_failed_extraction_stays_in_denominator():
    dataset = _dataset(failed_last=True).dataset
    scores = absa_scores(dataset, _gold())
    assert scores["category_micro"] == {"tp": 6, "fp": 0, "fn": 1}
    assert scores["joint_micro"] == {"tp": 6, "fp": 0, "fn": 1}
    assert scores["extraction_failed_ids"] == ["R04"]
    assert scores["extraction_success_rate"] == 3 / 4
    assert "conditioned_sentiment_macro_f1" not in scores


def test_conditioned_sentiment_is_scored_separately_with_missing_predictions():
    predictions = [
        ConditionedPrediction(record_id="R01", category="food", sentiment="positive"),
        ConditionedPrediction(record_id="R01", category="service", sentiment="negative"),
        ConditionedPrediction(record_id="R02", category="service", sentiment="negative"),
        ConditionedPrediction(record_id="R02", category="price", sentiment="negative"),
        ConditionedPrediction(record_id="R03", category="service", sentiment="neutral"),
        ConditionedPrediction(record_id="R03", category="food", sentiment="positive"),
    ]
    scores = conditioned_sentiment_scores(predictions, _gold())
    assert scores["expected_pairs"] == 7 and scores["received_pairs"] == 6
    assert scores["by_sentiment"]["positive"]["support"] == 3
    assert scores["by_sentiment"]["neutral"]["f1"] == 0
    assert scores["by_sentiment"]["conflict"]["f1"] is None
    assert scores["macro_f1"] == pytest.approx(0.6)
    with pytest.raises(ValueError):
        conditioned_sentiment_scores(predictions + [predictions[0]], _gold())


def test_answer_metrics_count_rate_undefined_and_false_refusal():
    count_reference = GoldReference(question_id="Q1", task_type="count", count=2)
    answer = AnswerPayload(method="b", question_id="Q1", status="ok", answer_text="2", numeric_claims=[{"metric": "negative_count", "category": "service", "value": 2}])
    assert score_answer(answer, count_reference)["primary_success"] is True
    refusal = AnswerPayload(method="b", question_id="Q1", status="insufficient_info", answer_text="No data")
    assert score_answer(refusal, count_reference)["false_refusal"] is True
    undefined = GoldReference(question_id="Q2", task_type="rate", numerator=0, denominator=0, rate=None)
    answer = AnswerPayload(method="b", question_id="Q2", status="ok", answer_text="undefined",
                           numeric_claims=[{"metric": "negative_rate", "category": "service", "value": None, "numerator": 0, "denominator": 0}],
                           denominator_explanation="No service mentions.")
    assert score_answer(answer, undefined)["primary_success"] is True
    answer.status = "partial"
    assert score_answer(answer, undefined)["primary_success"] is False


def test_selection_empty_rule_and_comparison_tie():
    selection = GoldReference(question_id="Q3", task_type="selection", selected_record_ids=[])
    answer = AnswerPayload(method="c", question_id="Q3", status="ok", answer_text="none")
    score = score_answer(answer, selection)
    assert score["selection_f1"] == 1 and score["selection_exact"] is True and score["primary_success"] is True
    comparison = GoldReference(question_id="Q4", task_type="comparison", comparison_groups=[["food", "service"]], category_counts={"food": 2, "service": 2})
    answer = AnswerPayload(method="b", question_id="Q4", status="ok", answer_text="tie", comparison_groups=[["food", "service"]],
                           numeric_claims=[{"metric": "negative_count", "category": category, "value": 2} for category in ["food", "service"]])
    assert score_answer(answer, comparison)["primary_success"] is True
    answer.comparison_groups = [["food"], ["service"]]
    assert score_answer(answer, comparison)["primary_success"] is False


def test_evidence_completion_checks_real_source_quote_and_summary_equal_weights():
    reference = GoldReference(question_id="Q5", task_type="evidence_explanation", comparison_groups=[["service"], ["price"], ["food"]],
                              category_counts={"food": 0, "service": 2, "price": 1}, source_record_ids=["R01", "R02"])
    answer = AnswerPayload(method="b", question_id="Q5", status="ok", answer_text="service first",
                           comparison_groups=[["service"], ["price"], ["food"]],
                           numeric_claims=[{"metric": "negative_count", "category": category, "value": count} for category, count in [("food", 0), ("service", 2), ("price", 1)]],
                           citations=[{"record_id": "R01", "quote": "service was slow"}])
    assert score_answer(answer, reference, _dataset().dataset.records)["primary_success"] is True
    answer.citations[0].quote = "invented"
    assert score_answer(answer, reference, _dataset().dataset.records)["primary_success"] is False
    summary = summarize_question_scores([
        {"task_type": "count", "primary_success": True, "false_refusal": False},
        {"task_type": "count", "primary_success": False, "false_refusal": True},
        {"task_type": "rate", "primary_success": True, "false_refusal": False},
    ])
    assert summary["per_type_success"] == {"count": 0.5, "rate": 1.0}
    assert summary["equal_type_average"] == 0.75 and summary["false_refusals"] == 1
