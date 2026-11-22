import pytest
from pydantic import ValidationError

from src.schemas import (
    AspectAnnotation, Coverage, ExtractionDataset, ExtractionResult,
    Predicate, QuerySpec, Record, RecordSet,
)


def test_record_preserves_text_and_generates_stable_id():
    text = "  The food was great.  "
    first = Record.model_validate({"text": text})
    assert first.text == text
    assert first.record_id == Record.model_validate({"text": text}).record_id
    assert first.record_id != Record.model_validate({"text": text.strip()}).record_id
    with pytest.raises(ValidationError):
        RecordSet(records=[first, first])


@pytest.mark.parametrize("value", ["", "  "])
def test_blank_text_fails(value):
    with pytest.raises(ValidationError):
        Record(record_id="R1", text=value)


def test_invalid_category_and_sentiment_fail():
    for data in [
        {"category": "anecdotes", "sentiment": "positive", "evidence": ["food"]},
        {"category": "food", "sentiment": "mixed", "evidence": ["food"]},
    ]:
        with pytest.raises(ValidationError):
            AspectAnnotation.model_validate(data)


def test_duplicate_category_and_failed_status_fail():
    aspect = AspectAnnotation(category="food", sentiment="positive", evidence=["food"])
    with pytest.raises(ValidationError):
        ExtractionResult(record_id="R1", aspects=[aspect, aspect], status="ok")
    with pytest.raises(ValidationError):
        ExtractionResult(record_id="R1", aspects=[], status="failed")
    with pytest.raises(ValidationError):
        ExtractionResult(record_id="R1", aspects=[], status="failed", error=" ")


def test_dataset_aligns_ids_coverage_and_exact_spans():
    record = Record(record_id="R1", text="The food was great.")
    good = ExtractionResult(record_id="R1", aspects=[AspectAnnotation(category="food", sentiment="positive", evidence=["food was great"])], status="ok")
    dataset = ExtractionDataset(fingerprint="abc", records=[record], extractions=[good], provider_model="mock", prompt_version="v1", schema_version="v1", coverage=Coverage(total=1, success=1))
    assert dataset.coverage.failed_ids == []
    bad_quote = good.model_copy(update={"aspects": [AspectAnnotation(category="food", sentiment="positive", evidence=["Food was great"])]})
    with pytest.raises(ValidationError, match="exact source substring"):
        ExtractionDataset(fingerprint="abc", records=[record], extractions=[bad_quote], provider_model="mock", prompt_version="v1", schema_version="v1", coverage=Coverage(total=1, success=1))
    with pytest.raises(ValidationError, match="IDs must match"):
        ExtractionDataset(fingerprint="abc", records=[record], extractions=[], provider_model="mock", prompt_version="v1", schema_version="v1", coverage=Coverage(total=1, success=1))


def test_query_conditions_do_not_form_cartesian_product():
    query = QuerySpec(task_type="selection", operator="AND", conditions=[Predicate(category="food", sentiment="positive"), Predicate(category="service", sentiment="negative")])
    assert [(c.category.value, c.sentiment.value) for c in query.conditions] == [("food", "positive"), ("service", "negative")]
    with pytest.raises(ValidationError):
        QuerySpec(task_type="selection", conditions=query.conditions)
    with pytest.raises(ValidationError):
        QuerySpec(task_type="rate", categories=["food"], metric="negative_rate")


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        Record.model_validate({"record_id": "R1", "text": "good", "rating": 5})
