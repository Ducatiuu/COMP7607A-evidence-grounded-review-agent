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


def test_blank_line_inside_quoted_review_is_text():
    records = read_csv(StringIO('text\n"First line\n\nSecond line"\n'))
    assert records.records[0].text == "First line\n\nSecond line"


@pytest.mark.parametrize("csv_text", [
    "rating\n5\n",
    "text,text\na,b\n",
    "text\n\n",
    "text\n  \n",
    "record_id,text\nR1,good\nR1,bad\n",
    "text\ngood\ngood\n",
    "text\ngood,extra\n",
])
def test_bad_csv_is_not_silently_filtered(csv_text):
    with pytest.raises(DataLoadError):
        read_csv(StringIO(csv_text))
