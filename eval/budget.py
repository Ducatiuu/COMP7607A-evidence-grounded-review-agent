"""Conservative planning arithmetic; no provider price is assumed."""

from __future__ import annotations

from pydantic import Field

from src.schemas.models import StrictModel


class PriceAssumptions(StrictModel):
    provider_model: str = Field(min_length=1)
    price_source: str = Field(min_length=1)
    price_date: str = Field(min_length=1)
    usd_per_million_input_tokens: float = Field(ge=0)
    usd_per_million_output_tokens: float = Field(ge=0)
    input_tokens_per_request_upper: int = Field(ge=1)
    output_tokens_per_request_upper: int = Field(ge=1)


def estimate_formal_budget(prices: PriceAssumptions) -> dict:
    answers = {"a": 160, "b": 190, "c": 220}
    query_requests_upper = answers["a"] + 3 * answers["b"] + 7 * answers["c"]
    main_extraction_requests_upper = 600 * 2
    challenge_extraction_requests_upper = 80 * 2
    requests_upper = query_requests_upper + main_extraction_requests_upper + challenge_extraction_requests_upper
    tokens_in_upper = requests_upper * prices.input_tokens_per_request_upper
    tokens_out_upper = requests_upper * prices.output_tokens_per_request_upper
    cost_upper = (tokens_in_upper * prices.usd_per_million_input_tokens +
                  tokens_out_upper * prices.usd_per_million_output_tokens) / 1_000_000
    return {"status": "ESTIMATE_ONLY", "provider_model": prices.provider_model,
            "price_source": prices.price_source, "price_date": prices.price_date,
            "answer_rows": answers, "answer_rows_total": sum(answers.values()),
            "query_requests_upper": query_requests_upper,
            "main_extraction_requests_upper": main_extraction_requests_upper,
            "challenge_extraction_requests_upper": challenge_extraction_requests_upper,
            "requests_upper": requests_upper, "input_tokens_upper": tokens_in_upper,
            "output_tokens_upper": tokens_out_upper, "cost_usd_upper": cost_upper,
            "excludes": ["pilot", "conditioned_sentiment", "optional_challenge_QA", "human_review"],
            "assumptions": "A 1, B 3, C 7 query requests per answer; extraction up to 2 requests per record; no cache credit"}
