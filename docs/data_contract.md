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

`QuerySpec` has an explicit task type, independent `(category, sentiment)` predicates and optional single-level AND/OR operator. Multiple conditions require an operator. Rate queries require `denominator_spec=aspect_mentions|all_records`. `metadata_required` can name date, rating or customer ID; the runtime must reject unsupported metadata analysis. A valid schema does not imply a query is answerable. Parser implementation and default policy are Phase 2 work.

```json
{"task_type":"selection","operator":"AND","conditions":[{"category":"food","sentiment":"positive"},{"category":"service","sentiment":"negative"}],"categories":[],"metric":null,"denominator_spec":null,"metadata_required":[],"needs_evidence":true}
```

## Answer and trace

`AnswerPayload` is the common output envelope for A/B/C, including failure and partial states, claims, complete selected ID set, citations, denominator explanation, coverage, trace, error code and usage. Failure requires an error code. `TraceEvent` records the action and outcome, not private chain of thought. `ToolResult` carries an explicit status and coverage. Semantic evidence quality needs independent assessment; structural checks only establish ID, quote and numerical consistency.

The offline `LLMClient.complete_json(LLMRequest) -> LLMResponse` protocol permits dependency injection. `MockLLMClient` returns only supplied fixtures, logs requests, and fails when its queue is exhausted. It is not a live provider or an ABSA algorithm.

## Extraction service

`ExtractionService.extract(RecordSet) -> ExtractionRun` processes each record in input order. Each record gets at most one initial request and one extraction retry; failed attempts remain `status=failed` in the dataset after that. The service validates returned ID, schema, category uniqueness, exact spans and actual model identifier. Its cache key hashes canonical JSON of original text, provider/model, prompt version, schema version and extraction configuration. Cache entries hold aspects without record IDs; hits are rebound to the current record and revalidated. Only validated successes are cached. `requests`, `retries` and `cache_hits` describe physical calls and reuse separately. Disk cache is optional and should live under ignored `outputs/`.
