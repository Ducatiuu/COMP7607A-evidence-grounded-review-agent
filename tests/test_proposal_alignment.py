"""Independent hand checks for the Proposal's four illustrative records."""

from pathlib import Path

from src.absa_service import ExtractionService
from src.data_loader import load_csv
from src.demo_mock import mock_for_demo
from src.tools import AggregateArgs, AnalysisContext, FilterArgs, aggregate_aspects, filter_records


ROOT = Path(__file__).resolve().parents[1]


def test_proposal_example_texts_counts_and_conjunction():
    records = load_csv(ROOT / "data/demo/core.csv")
    assert [(item.record_id, item.text) for item in records.records] == [
        ("R01", "The food was great, but the service was slow."),
        ("R02", "Delicious food, but far too expensive."),
        ("R03", "Friendly staff and quick service."),
        ("R04", "Cold food and a long wait."),
    ]
    dataset = ExtractionService(mock_for_demo(records, method="extract"), provider_model="mock").extract(records).dataset
    context = AnalysisContext(dataset)
    aggregate = aggregate_aspects(context, AggregateArgs(categories=["service", "price", "ambience"], metric="negative_rate"))
    by_category = {item.category.value: item for item in aggregate.stats}
    assert (by_category["service"].mention_count, by_category["service"].negative_count,
            by_category["service"].rate) == (3, 2, 2 / 3)
    assert (by_category["price"].mention_count, by_category["price"].negative_count,
            by_category["price"].rate) == (1, 1, 1)
    assert by_category["ambience"].mention_count == 0 and by_category["ambience"].rate is None
    selected = filter_records(context, FilterArgs(conditions=[{"category": "food", "sentiment": "positive"},
                                                          {"category": "service", "sentiment": "negative"}], operator="AND"))
    assert selected.record_ids == ["R01"]
