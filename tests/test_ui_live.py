from collections import deque
from pathlib import Path

import pytest

from src.data_loader import read_csv
from src.llm_client import LLMResponse, MockLLMClient
from src.ui_live import run_live_answer, run_live_extraction


def test_uploaded_csv_live_backend_extracts_and_answers_with_durable_trace(tmp_path, monkeypatch):
    import io
    import src.ui_live as ui_live

    records = read_csv(io.StringIO("record_id,text\nU1,Service was slow.\n"))
    extraction_client = MockLLMClient(deque([LLMResponse(
        content={"record_id": "U1", "status": "ok", "aspects": [{"category": "service", "sentiment": "negative",
                                                                    "evidence": ["Service was slow"]}]},
        model="deepseek-flash", input_tokens=100, output_tokens=30)]))
    monkeypatch.setattr(ui_live, "require_dev_run_balance", lambda cap: None)
    monkeypatch.setattr(ui_live, "ResponsesClient", lambda *args, **kwargs: extraction_client)
    dataset, extraction_summary = run_live_extraction(records, source_label="Uploaded: sample.csv", root=tmp_path)
    assert dataset.coverage.success == 1 and extraction_summary["requests"] == 1
    assert (Path(extraction_summary["run_directory"]) / "calls.jsonl").exists()

    answer_client = MockLLMClient(deque([
        LLMResponse(content={"task_type": "rate", "categories": ["service"],
                             "metric": "negative_rate", "denominator_spec": "aspect_mentions"},
                    model="deepseek-flash", input_tokens=100, output_tokens=30),
        LLMResponse(content={"status": "ok", "answer_text": "One of one service reviews is negative.",
                             "numeric_claims": [{"metric": "negative_rate", "category": "service",
                                                 "scope_ids": ["U1"], "value": 1.0,
                                                 "numerator": 1, "denominator": 1, "unit": "fraction"}],
                             "denominator_explanation": "One scoped record mentions service."},
                    model="deepseek-flash", input_tokens=120, output_tokens=45),
    ]))
    monkeypatch.setattr(ui_live, "ResponsesClient", lambda *args, **kwargs: answer_client)
    answer, summary = run_live_answer(records, question="What fraction of service reviews are negative?",
                                      method="b", extraction=dataset,
                                      source_label="Uploaded: sample.csv", root=tmp_path)
    assert answer.status == "ok" and answer.numeric_claims[0].denominator == 1
    assert answer.numeric_claims[0].unit == "fraction"
    assert summary["verification_scope"] == "tool_and_source_consistency"
    assert summary["requests"] == 2 and len(list(tmp_path.iterdir())) == 2


def test_live_ui_rejects_stale_price_before_balance_or_network(tmp_path, monkeypatch):
    import io
    import src.ui_live as ui_live

    records = read_csv(io.StringIO("text\nBad service.\n"))
    monkeypatch.setattr(ui_live, "PRICE_DATE", "2000-01-01")
    monkeypatch.setattr(ui_live, "require_dev_run_balance",
                        lambda cap: pytest.fail("balance should not be queried for stale pricing"))
    with pytest.raises(ValueError, match="price verification date is stale"):
        run_live_extraction(records, source_label="test", root=tmp_path)
    assert list(tmp_path.iterdir()) == []
