from collections import deque
from decimal import Decimal

import pytest

from src.live_cost import BudgetError, CostLimitedClient, plan_cost
from src.llm_client import LLMRequest, LLMResponse, MockLLMClient


def _plan(**overrides):
    values = {"max_requests": 2, "max_input_tokens_per_request": 100_000,
              "max_output_tokens_per_request": 100_000, "input_usd_per_million": "1",
              "output_usd_per_million": "2", "max_cost_usd": "0.6",
              "price_source": "fixture://not-a-quote", "price_date": "2026-11-22"}
    values.update(overrides)
    return plan_cost(**values)


def _request():
    return LLMRequest(stage="extract", system_prompt="Return JSON", payload={}, schema_name="ExtractionResult")


def _reply(input_tokens, output_tokens):
    return LLMResponse(content={}, model="fixture", input_tokens=input_tokens, output_tokens=output_tokens)


def test_exact_decimal_preflight_and_known_usage():
    plan = _plan()
    assert plan.worst_case_usd == Decimal("0.6")
    client = MockLLMClient(deque([_reply(100_000, 100_000), _reply(100_000, 100_000)]))
    guarded = CostLimitedClient(client, plan)
    guarded.complete_json(_request())
    guarded.complete_json(_request())
    assert guarded.requests == 2 and guarded.estimated_cost_usd == Decimal("0.6")
    with pytest.raises(BudgetError, match="closed"):
        guarded.complete_json(_request())
    assert len(client.requests) == 2


def test_inadequate_cap_or_bad_price_rejected_before_calls():
    with pytest.raises(BudgetError, match="worst case"):
        _plan(max_cost_usd="0.599999")
    for bad in ("nan", "-1", "0", True):
        with pytest.raises(ValueError):
            _plan(input_usd_per_million=bad)
    with pytest.raises(ValueError, match="positive integer"):
        _plan(max_requests=True)
    with pytest.raises(ValueError, match="price source"):
        _plan(price_source="")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _plan(price_date="yesterday")


@pytest.mark.parametrize("input_tokens,output_tokens", [(None, 1), (True, 1), (1, -1), (100_001, 1), (1, 100_001)])
def test_unknown_or_out_of_bound_usage_freezes_future_calls(input_tokens, output_tokens):
    client = MockLLMClient(deque([_reply(input_tokens, output_tokens), _reply(1, 1)]))
    guarded = CostLimitedClient(client, _plan())
    with pytest.raises(BudgetError, match="usage"):
        guarded.complete_json(_request())
    with pytest.raises(BudgetError, match="closed"):
        guarded.complete_json(_request())
    assert guarded.requests == 1 and guarded.estimated_cost_usd is None
    assert len(client.requests) == 1


def test_transport_error_keeps_attempt_and_freezes_future_calls():
    client = MockLLMClient(deque([TimeoutError("offline failure"), _reply(1, 1)]))
    guarded = CostLimitedClient(client, _plan())
    with pytest.raises(TimeoutError):
        guarded.complete_json(_request())
    with pytest.raises(BudgetError, match="closed"):
        guarded.complete_json(_request())
    assert guarded.requests == 1 and guarded.estimated_cost_usd is None
    assert len(client.requests) == 1
