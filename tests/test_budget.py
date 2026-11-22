import pytest
from pydantic import ValidationError

from eval.budget import PriceAssumptions, estimate_formal_budget


def test_budget_arithmetic_is_explicit_and_excludes_pilot():
    prices = PriceAssumptions(provider_model="synthetic-price-example", price_source="fixture-only", price_date="2026-01-01",
                              usd_per_million_input_tokens=1, usd_per_million_output_tokens=2,
                              input_tokens_per_request_upper=1000, output_tokens_per_request_upper=500)
    result = estimate_formal_budget(prices)
    assert result["answer_rows"] == {"a": 160, "b": 190, "c": 220}
    assert result["answer_rows_total"] == 570
    assert result["query_requests_upper"] == 2270 and result["requests_upper"] == 3630
    assert result["cost_usd_upper"] == 7.26 and "pilot" in result["excludes"]
    with pytest.raises(ValidationError):
        PriceAssumptions.model_validate({**prices.model_dump(), "usd_per_million_input_tokens": -1})
