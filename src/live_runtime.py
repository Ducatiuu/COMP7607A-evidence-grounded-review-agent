"""Model-backed A/B/C orchestration for caller-supplied restaurant records.

The caller supplies the model client and an explicit request ceiling. No CLI or UI
enables network use here; the real Provider adapter stays network-disabled by default.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from src.absa_service import ExtractionService
from src.controllers import DirectLLM, DynamicAgent, FixedWorkflow, QueryParser
from src.data_loader import dataset_fingerprint
from src.llm_client import LLMClient, LLMRequest, LLMResponse
from src.live_cost import CostLimitedClient
from src.schemas import AnswerPayload, ExtractionDataset, RecordSet
from src.tools import AnalysisContext
from src.verification import Finalizer


class RequestLimitError(RuntimeError):
    pass


def _add_known_tokens(total: int | None, amount: object) -> int | None:
    return total + amount if total is not None and type(amount) is int and amount >= 0 else None


@dataclass
class RequestLimitedClient:
    delegate: LLMClient
    max_requests: int
    requests: int = 0
    input_tokens: int | None = 0
    output_tokens: int | None = 0

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        if self.requests >= self.max_requests:
            raise RequestLimitError("model request limit reached")
        self.requests += 1  # Count attempted requests, including transport failures.
        try:
            response = self.delegate.complete_json(request)
        except Exception:
            self.input_tokens = self.output_tokens = None
            raise
        self.input_tokens = _add_known_tokens(self.input_tokens, response.input_tokens)
        self.output_tokens = _add_known_tokens(self.output_tokens, response.output_tokens)
        return response


@dataclass(frozen=True)
class ModelRun:
    answer: AnswerPayload
    extraction_dataset: ExtractionDataset | None
    dataset_sha256: str
    requests: int
    extraction_requests: int
    request_ceiling: int
    input_tokens: int | None
    output_tokens: int | None


def conservative_request_bound(method: Literal["a", "b", "c"], record_count: int,
                               *, prepared_extraction: bool = False) -> int:
    if method not in {"a", "b", "c"} or type(record_count) is not int or record_count < 1:
        raise ValueError("valid method and positive record count required")
    extraction_bound = 0 if method == "a" or prepared_extraction else 2 * record_count
    return extraction_bound + {"a": 1, "b": 3, "c": 7}[method]


def run_model_method(
    records: RecordSet, *, method: Literal["a", "b", "c"], question: str,
    client: LLMClient, model_id: str, max_api_requests: int,
    max_records: int, max_input_chars: int,
    question_id: str | None = None,
    extraction_dataset: ExtractionDataset | None = None,
    extraction_prompt_version: str = "extract-v1",
    query_prompt_version: str = "query-v1",
    answer_prompt_version: str = "answer-v1",
    decision_prompt_version: str = "decision-v1",
) -> ModelRun:
    """Execute one bounded method run on non-demo records; keep B/C setup reusable."""
    if method not in {"a", "b", "c"} or not isinstance(question, str) or not question.strip():
        raise ValueError("method A/B/C and a nonempty question required")
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("nonempty model ID required")
    if not records.records or type(max_records) is not int or max_records < 1 or len(records.records) > max_records:
        raise ValueError("record count exceeds configured limit")
    if type(max_input_chars) is not int or max_input_chars < 1:
        raise ValueError("positive input character limit required")
    if sum(len(record.text) for record in records.records) + len(question) > max_input_chars:
        raise ValueError("source text and question exceed configured input character limit")
    if method == "a" and extraction_dataset is not None:
        raise ValueError("Method A cannot use extraction")
    if extraction_dataset is not None and (extraction_dataset.records != records.records
                                           or extraction_dataset.fingerprint != dataset_fingerprint(records)
                                           or extraction_dataset.provider_model != model_id
                                           or extraction_dataset.prompt_version != extraction_prompt_version):
        raise ValueError("supplied extraction does not match records or model")

    bound = conservative_request_bound(method, len(records.records),
                                       prepared_extraction=extraction_dataset is not None)
    if type(max_api_requests) is not int or max_api_requests < bound:
        raise ValueError(f"request ceiling must allow the conservative {bound}-request bound")

    if isinstance(client, CostLimitedClient):
        if client.plan.max_requests != max_api_requests or client.requests != 0:
            raise ValueError("fresh cost plan must match the request ceiling")
        counted = client
    else:
        counted = RequestLimitedClient(client, max_api_requests)
    fingerprint = dataset_fingerprint(records)
    if method == "a":
        query_started = time.perf_counter()
        answer = DirectLLM(counted, model_id).run(records=records, question=question, question_id=question_id)
        answer = answer.model_copy(update={"usage": {**answer.usage,
            "api_requests": counted.requests, "input_tokens": counted.input_tokens,
            "output_tokens": counted.output_tokens,
            "query_wall_latency_ms": (time.perf_counter() - query_started) * 1000}})
        return ModelRun(answer=answer, extraction_dataset=None, dataset_sha256=fingerprint,
                        requests=counted.requests, extraction_requests=0, request_ceiling=max_api_requests,
                        input_tokens=counted.input_tokens, output_tokens=counted.output_tokens)

    extraction_requests = 0
    extraction_wall_ms = None
    if extraction_dataset is None:
        started = time.perf_counter()
        extraction = ExtractionService(counted, provider_model=model_id,
                                       prompt_version=extraction_prompt_version).extract(records)
        extraction_dataset = extraction.dataset
        extraction_requests = extraction.requests
        extraction_wall_ms = (time.perf_counter() - started) * 1000
    query_started = time.perf_counter()
    ctx = AnalysisContext(extraction_dataset)
    parser = QueryParser(counted, model_id, prompt_version=query_prompt_version)
    finalizer = Finalizer(counted, model_id, prompt_version=answer_prompt_version)
    if method == "b":
        answer = FixedWorkflow(parser, finalizer).run(ctx=ctx, question=question, question_id=question_id)
    else:
        answer = DynamicAgent(parser, counted, finalizer, model_id,
                              decision_prompt_version=decision_prompt_version).run(
                                  ctx=ctx, question=question, question_id=question_id)
    usage = {**answer.usage, "api_requests": counted.requests, "extraction_requests": extraction_requests,
             "input_tokens": counted.input_tokens, "output_tokens": counted.output_tokens,
             "query_wall_latency_ms": (time.perf_counter() - query_started) * 1000}
    if extraction_wall_ms is not None:
        usage["extraction_wall_latency_ms"] = extraction_wall_ms
    answer = answer.model_copy(update={"usage": usage})
    return ModelRun(answer=answer, extraction_dataset=extraction_dataset,
                    dataset_sha256=fingerprint, requests=counted.requests,
                    extraction_requests=extraction_requests, request_ceiling=max_api_requests,
                    input_tokens=counted.input_tokens, output_tokens=counted.output_tokens)
