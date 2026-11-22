from collections import deque

from eval.conditioned import ConditionedSentimentService, GoldCategoryInput
from eval.metrics import conditioned_sentiment_scores
from src.llm_client import LLMResponse, MockLLMClient
from src.schemas import Record, RecordSet
from src.semeval import GoldRecord


def test_conditioned_prompt_receives_categories_but_no_gold_sentiments():
    records = RecordSet(records=[Record(record_id="R1", text="Good food, slow service.")])
    inputs = [GoldCategoryInput(record_id="R1", categories=["food", "service"])]
    client = MockLLMClient(deque([LLMResponse(content={"record_id": "R1", "sentiments": [["food", "positive"], ["service", "negative"]]}, model="mock")]))
    run = ConditionedSentimentService(client, "mock").classify(records, inputs)
    assert run.requests == 1 and run.failed_ids == []
    assert client.requests[0].payload["categories"] == ["food", "service"]
    assert "positive" not in str(client.requests[0].payload) and "negative" not in str(client.requests[0].payload)
    gold = [GoldRecord(record_id="R1", aspects=[{"category": "food", "sentiment": "positive"}, {"category": "service", "sentiment": "negative"}])]
    assert conditioned_sentiment_scores(run.predictions, gold)["macro_f1"] == 1.0


def test_conditioned_mismatch_retries_once_then_retains_failures():
    records = RecordSet(records=[Record(record_id="R1", text="Good food")])
    inputs = [GoldCategoryInput(record_id="R1", categories=["food"])]
    client = MockLLMClient(deque([LLMResponse(content={"record_id": "wrong", "sentiments": [["food", "positive"]]}, model="mock"), TimeoutError()]))
    run = ConditionedSentimentService(client, "mock").classify(records, inputs)
    assert run.requests == 2 and run.retries == 1 and run.failed_ids == ["R1"]
    assert run.predictions[0].status == "failed" and run.predictions[0].sentiment is None
