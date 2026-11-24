from io import StringIO

import pytest

from src.data_loader import DataLoadError, dataset_fingerprint, load_csv, read_csv


def test_core_demo_is_four_synthetic_records():
    records = load_csv("data/demo/core.csv")
    assert [r.record_id for r in records.records] == ["R01", "R02", "R03", "R04"]
    assert records.records[0].text == "The food was great, but the service was slow."
    assert dataset_fingerprint(records) == dataset_fingerprint(load_csv("data/demo/core.csv"))


def test_text_only_csv_stable_id_and_original_whitespace():
    records = read_csv(StringIO('text,rating\n"  Nice food.  ",5\n'))
    assert records.records[0].text == "  Nice food.  "
    assert records.records[0].record_id.startswith("auto-")
    assert dataset_fingerprint(records) != dataset_fingerprint(read_csv(StringIO('text\nNice food.\n')))


def test_repeated_reviews_get_distinct_deterministic_ids():
    source = 'review,rating\n"Nice food",5\n"Nice food",4\n'
    first = read_csv(StringIO(source), text_column="review")
    second = read_csv(StringIO(source), text_column="review")
    assert len(first.records) == 2
    assert [record.record_id for record in first.records] == [record.record_id for record in second.records]
    assert first.records[0].record_id != first.records[1].record_id
    assert [record.text for record in first.records] == ["Nice food", "Nice food"]


def test_explicit_text_and_id_column_mapping():
    records = read_csv(StringIO('row_id,review,rating\n A1 ,"  Great food.  ",5\n'),
                       text_column="review", id_column="row_id")
    assert records.records[0].record_id == "A1"
    assert records.records[0].text == "  Great food.  "


def test_semeval_loader_can_preserve_source_id_whitespace_without_changing_default():
    source = 'record_id,text\n"33068425#562449#4 ",A review.\n'
    ordinary = read_csv(StringIO(source))
    original = read_csv(StringIO(source), preserve_explicit_ids=True)
    assert ordinary.records[0].record_id == "33068425#562449#4"
    assert original.records[0].record_id == "33068425#562449#4 "
    assert dataset_fingerprint(ordinary) != dataset_fingerprint(original)
    with pytest.raises(DataLoadError, match="blank record ID"):
        read_csv(StringIO('record_id,text\n"   ",A review.\n'), preserve_explicit_ids=True)


def test_blank_line_inside_quoted_review_is_text():
    records = read_csv(StringIO('text\n"First line\n\nSecond line"\n'))
    assert records.records[0].text == "First line\n\nSecond line"


@pytest.mark.parametrize("csv_text", [
    "rating\n5\n",
    "text,text\na,b\n",
    "text\n\n",
    "text\n  \n",
    "record_id,text\nR1,good\nR1,bad\n",
    "text\ngood,extra\n",
    "record_id,text\n,good\n",
    "text\n",
])
def test_bad_csv_is_not_silently_filtered(csv_text):
    with pytest.raises(DataLoadError):
        read_csv(StringIO(csv_text))


def test_invalid_column_mapping_is_rejected():
    with pytest.raises(DataLoadError, match="distinct"):
        read_csv(StringIO("text\nNice food\n"), text_column="text", id_column="text")
    with pytest.raises(DataLoadError, match="requires"):
        read_csv(StringIO("review\nNice food\n"))
