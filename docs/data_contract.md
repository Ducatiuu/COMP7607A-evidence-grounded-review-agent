# Data contract v1 (Phase 0)

All external and cross-module objects use Pydantic v2 models in `src/schemas/models.py`. Unknown fields are errors. String enums are lowercase except Boolean operators. JSON examples below are synthetic.

## Records and extraction

`Record(record_id: str, text: str)` preserves exact input text. A missing or blank ID becomes `auto-` plus the first 16 hexadecimal characters of SHA-256 of UTF-8 original text. Duplicate IDs, including identical texts with generated IDs, are rejected by `RecordSet`. Empty or whitespace-only text is rejected. Text normalization is never applied to stored records.

`load_csv(path)` and `read_csv(stream)` require a `text` header; `record_id` is optional. Extra CSV columns are ignored as data, not made available as analytical metadata. Header duplication, surplus cells, blank text and duplicate IDs fail the whole load with a row-aware error when possible. Explicit CSV IDs are stripped; text is not. `dataset_fingerprint` hashes ordered record ID/text pairs using canonical JSON and SHA-256.

`ExtractionResult` uses `status=ok` for valid results (an empty aspect list is allowed) and `status=failed` plus a nonempty error for failures. A failed result has no aspects. Each category occurs at most once per record. Every evidence span must be a nonblank, exact substring of the original record text. `ExtractionDataset` requires one result per record with exactly matching IDs; its coverage and failure IDs must agree with actual results. This validation does not establish that a quoted span supports the sentiment semantically.

```json
{"record_id":"R01","aspects":[{"category":"food","sentiment":"positive","evidence":["The food was great"]}],"status":"ok","error":null}
```

## Queries

`QuerySpec` has an explicit task type, independent `(category, sentiment)` predicates and optional single-level AND/OR operator. Multiple conditions require an operator. Rate queries require `denominator_spec=aspect_mentions|all_records`. `metadata_required` can name date, rating or customer ID; the runtime must reject unsupported metadata analysis. A valid schema does not imply a query is answerable. A rate query may filter an independent subgroup, but it rejects a negative sentiment filter on its own target category because filtering before aggregation would remove the denominator's nonnegative records.

For each target category, `negative_rate` counts **distinct review records**. The numerator is the number of scoped records labelled negative for that category. With `aspect_mentions`, the denominator is the number of scoped records mentioning that category with any sentiment; this name does not count multiple text spans. With `all_records`, the denominator is the number of all scoped records. Conflict contributes to a mention denominator but not to the negative numerator. A zero denominator yields `null`; the numeric claim's unit is `fraction`, so 0.25 means 25%. `src.rate_semantics.rate_definition` carries these definitions in the versioned answer request; the deterministic tool computes the counts, and the answer verifier checks the returned claim and unit.

```json
{"task_type":"selection","operator":"AND","conditions":[{"category":"food","sentiment":"positive"},{"category":"service","sentiment":"negative"}],"categories":[],"metric":null,"denominator_spec":null,"metadata_required":[],"needs_evidence":true}
```

## Answer and trace

`AnswerPayload` is the common output envelope for A/B/C, including failure and partial states, claims, complete selected ID set, citations, denominator explanation, coverage, trace, error code and usage. Failure requires an error code. `TraceEvent` records the action and outcome, not private chain of thought. `ToolResult` carries an explicit status and coverage. Semantic evidence quality needs independent assessment; structural checks only establish ID, quote and numerical consistency.

`comparison_groups` is an ordered list of tied category groups. B/C output checks compare it with the actual comparison tool result. A gets only common schema validation. B/C numeric claims must match real tool values, query scope and denominator type; selection IDs must match a full-scope filter of the QuerySpec predicates. Citation quotes must be exact original substrings and their IDs must have been retrieved by the evidence tool. These checks do not prove the semantic content of prose or the relevance of a quote.

The offline `LLMClient.complete_json(LLMRequest) -> LLMResponse` protocol permits dependency injection. `MockLLMClient` returns only supplied fixtures, logs requests, and fails when its queue is exhausted. It is not a live provider or an ABSA algorithm.

## Extraction service

`ExtractionService.extract(RecordSet) -> ExtractionRun` processes each record in input order. Each record gets at most one initial request and one extraction retry; failed attempts remain `status=failed` in the dataset after that. The service validates returned ID, schema, category uniqueness, exact spans and actual model identifier. Its cache key hashes canonical JSON of original text, provider/model, prompt version, schema version and extraction configuration. Cache entries hold aspects without record IDs; hits are rebound to the current record and revalidated. Only validated successes are cached. `requests`, `retries` and `cache_hits` describe physical calls and reuse separately. Disk cache is optional and should live under ignored `outputs/`.

## Dynamic control budget

`DynamicAgent` shares the parser, extraction dataset, tool dispatcher, finalizer and verifier with B. It asks the model to choose JSON actions after each actual tool result. A decision request counts one round even when malformed or timed out; maximum four rounds. Each submitted tool call, including unknown, invalid or duplicate calls, counts once; maximum six calls. A multi-call action stops before the seventh call. Parser, answer and at most one output repair are separate model requests and do not reset dynamic counters. The trace stores decision action summaries and tool IDs/counts; evidence trace summaries omit raw review text. Unknown token usage remains null. An answer may complete at a budget boundary if existing verified evidence suffices.
