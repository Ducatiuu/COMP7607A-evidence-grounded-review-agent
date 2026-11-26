# Formal A/B/C runner — Stage 2

This is an execution implementation and an **offline validation result**, not a formal experiment result. The fixed set remains P01/P06/P11/P16, 120 reviews, 24 unique questions and 72 A/B/C answer slots. The R1 and R2 `02_questions/reviewer_N.csv` files contain the **same** 24 questions for independent review. The 13-row `01_extraction` sheets are development diagnostics, not formal question inputs.

## Safety precheck

`python -m scripts.run_formal_experiment --plan <saved-plan.json> --reviewer-1 <R1-question-CSV-or-packet.zip> --reviewer-2 <R2-question-CSV-or-packet.zip>` is read-only and has no network path. The current candidate plan is rejected because the two question reviews, adjudication and signed freeze are pending. It needs no DeepSeek key. The existing saved Stage 1 candidate plan stays candidate-only; a **new** plan must be created after review and freeze.

Before any future live run, `checked_plan` reconstructs Stage 1 preflight from the original locked Pack IDs, 24 question IDs, 150/600 split, test and development CSVs, questions, references, Gold hash, metrics-code hash, both completed reviewer sheets, adjudication and freeze manifests. The full rebuilt plan must equal the saved plan field-for-field as a JSON object, including its fingerprint. Editing `execution_permitted`, `formal_runner_implemented`, `material_gate_passed` or any other single field cannot unlock the runner. Stage 1 deliberately leaves its own `execution_permitted=false`; the Stage 2 gate depends on fresh material validation and separate live authorization.

After real human review and freeze, a planned live call would additionally require `--execute --authorize-formal-live --plan-sha256 <exact hash>`, an available environment key, dated prices no more than seven days old, and the existing official balance reserve check. These code flags do not replace the project owner's separate approval for the formal holdout. **No such approval or freeze exists at Stage 2. Do not use these live flags yet.** The provider adapter itself has no automatic HTTP retry.

## Method and saved files

Each Pack runs one shared ABSA extraction. Method A receives only its 30 raw review texts and the question. B and C receive the same validated, hash-bound extraction dataset; B uses the fixed workflow, C uses the dynamic controller and existing verifier. No Prompt or Agent algorithm was changed. Only the original question wording reaches the methods. Gold and candidate references are loaded by the separate preflight gate for hash and question integrity, then excluded from the model loop.

A run directory is unique and local; real data and output stay under ignored `outputs/`. Its files are:

| File | Contents |
|---|---|
| `run_manifest.json` | Full checked plan, model, Prompt versions, source hashes, task IDs and mode |
| `extractions/Pxx.json` | Shared ABSA data, model and source fingerprint per Pack |
| `tasks.jsonl` | Durable begin/complete/failed events with task IDs and artifact hashes |
| `calls.jsonl` | Durable request begin/end, Pack/question/method/stage, request and response hashes, local request/response payloads, Token counts, latency and safe error type |
| `results.jsonl` | Every completed answer or method failure, status, Pack/question/method IDs, request count and shared extraction hash |
| `summary.json` | COMPLETE, PAUSED or PARTIAL; request/Token/cost totals and 72-answer progress; no formal score |

Request payloads and answers can contain restricted review text and must never be published. API keys and Authorization headers are never written. Token/cost figures are estimates based on declared rates and observed usage, not an invoice. The 504 request ceiling is a conservative **maximum**, not a forecast of actual calls. Unknown usage, over-limit usage or a transport error freezes the cost gate.

`COMPLETE` means all 72 answer slots were recorded; it does **not** mean the answers are correct or even all `ok`. The summary separately counts answer statuses, including refusal and failure. No formal score is calculated in this stage.

## Recovery and limits

An offline test may pause at a fully written task boundary. Resume reruns preflight, checks the original plan, mode, ordered task IDs, extraction/result hashes, every begin/end request pair, Token bounds, cumulative cost and per-task request totals. Only completed tasks are skipped. An in-flight request, failed task, unknown outcome, missing usage, changed input, changed answer/extraction artifact or inconsistent journal blocks automatic resume; someone must inspect the local run instead of repeating a possibly charged request. Refusals and partial/failed answers remain in `results.jsonl` or extraction/call journals and are never silently filtered out.

The synthetic tests exercise all 72 answer slots, ordering and sharing, safe pause/resume, request failure, unknown request and Token ceiling. They do not measure real model quality. Stage 3 must add independent offline scoring against the finally frozen Gold/reference/rubric, reconcile answer and call counts, and produce the research result tables and error analysis without feeding Gold back into the runtime.
