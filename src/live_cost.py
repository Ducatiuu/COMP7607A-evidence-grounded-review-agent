"""Conservative client-side spend estimate for explicitly priced live calls.

Provider bills may differ. A caller must verify the model, current price, cache
policy and data scope before enabling a network client.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re

from src.llm_client import LLMClient, LLMRequest, LLMResponse


class BudgetError(RuntimeError):
    pass


def _positive_decimal(value: object, name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a finite positive decimal") from None
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{name} must be a finite positive decimal")
    return amount


@dataclass(frozen=True)
class CostPlan:
    max_requests: int
    max_input_tokens_per_request: int
    max_output_tokens_per_request: int
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    max_cost_usd: Decimal
    price_source: str
    price_date: str
    worst_case_usd: Decimal

    @property
    def per_request_bound_usd(self) -> Decimal:
        return self.worst_case_usd / self.max_requests


def plan_cost(*, max_requests: int, max_input_tokens_per_request: int,
              max_output_tokens_per_request: int, input_usd_per_million: object,
              output_usd_per_million: object, max_cost_usd: object,
              price_source: str, price_date: str) -> CostPlan:
    counts = (max_requests, max_input_tokens_per_request, max_output_tokens_per_request)
    if any(type(value) is not int or value < 1 for value in counts):
        raise ValueError("positive integer request and token limits required")
    if not isinstance(price_source, str) or not price_source.strip() or not isinstance(price_date, str) or not price_date.strip():
        raise ValueError("price source and date required")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", price_date):
        raise ValueError("price date must be YYYY-MM-DD")
    try:
        date.fromisoformat(price_date)
    except ValueError:
        raise ValueError("price date must be YYYY-MM-DD") from None
    input_price = _positive_decimal(input_usd_per_million, "input price")
    output_price = _positive_decimal(output_usd_per_million, "output price")
    cap = _positive_decimal(max_cost_usd, "cost cap")
    worst = Decimal(max_requests) * (Decimal(max_input_tokens_per_request) * input_price
                                      + Decimal(max_output_tokens_per_request) * output_price) / Decimal(1_000_000)
    if worst > cap:
        raise BudgetError("declared request/token worst case exceeds cost cap")
    return CostPlan(max_requests, max_input_tokens_per_request, max_output_tokens_per_request,
                    input_price, output_price, cap, price_source.strip(), price_date.strip(), worst)


@dataclass
class CostLimitedClient:
    delegate: LLMClient
    plan: CostPlan
    requests: int = 0
    input_tokens: int | None = 0
    output_tokens: int | None = 0
    estimated_cost_usd: Decimal | None = Decimal(0)
    frozen: bool = False

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        if self.frozen or self.requests >= self.plan.max_requests:
            raise BudgetError("live cost/request gate is closed")
        if self.estimated_cost_usd is None or self.estimated_cost_usd + self.plan.per_request_bound_usd > self.plan.max_cost_usd:
            raise BudgetError("next request exceeds declared cost cap")
        self.requests += 1
        try:
            response = self.delegate.complete_json(request)
        except Exception:
            self.estimated_cost_usd = None
            self.input_tokens = self.output_tokens = None
            self.frozen = True
            raise
        input_tokens, output_tokens = response.input_tokens, response.output_tokens
        if (type(input_tokens) is not int or type(output_tokens) is not int
                or input_tokens < 0 or output_tokens < 0
                or input_tokens > self.plan.max_input_tokens_per_request
                or output_tokens > self.plan.max_output_tokens_per_request):
            self.estimated_cost_usd = None
            self.input_tokens = self.output_tokens = None
            self.frozen = True
            raise BudgetError("provider token usage missing or outside declared bound")
        self.input_tokens = self.input_tokens + input_tokens if self.input_tokens is not None else None
        self.output_tokens = self.output_tokens + output_tokens if self.output_tokens is not None else None
        estimate = (Decimal(input_tokens) * self.plan.input_usd_per_million
                    + Decimal(output_tokens) * self.plan.output_usd_per_million) / Decimal(1_000_000)
        self.estimated_cost_usd += estimate
        if self.estimated_cost_usd > self.plan.max_cost_usd:
            self.frozen = True
            raise BudgetError("known token estimate exceeds declared cost cap")
        return response
