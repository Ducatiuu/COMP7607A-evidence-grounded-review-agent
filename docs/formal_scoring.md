# Formal scoring and reconciliation — Stage 3

The scorer is local and read-only. It does not construct a provider client, call DeepSeek, change the Agent or compute a grade from the current unreviewed candidate references. Stage 3 implementation was tested only with synthetic reviews, mock calls and fixture-only review/freeze records.

## Required human release

The Stage 1 release must pass the existing R1/R2 review, adjudication, source hash, question ID and scoring-rule checks. Before scoring, the human-signed `FROZEN` release must **also** bind a separate final reference file with:

```json
{
  "scoring_reference_status": "HUMAN_CONFIRMED",
  "scoring_reference_sha256": "<SHA-256 of the final 24-reference JSON>",
  "scoring_reference_question_ids": ["<the same 24 ordered IDs in the locked plan>"]
}
```

The final JSON has 24 `GoldReference` rows in locked question order. It may preserve an approved original answer or contain a human-adjudicated correction. The existing candidate files and lock are never overwritten. The `GoldReference.status` field is a legacy candidate schema marker; the signed release and final-file hash carry the human-confirmed provenance. The scorer also rejects inconsistent count/rate values and duplicate or out-of-Pack record IDs. A reviewer rejection alone is not a corrected reference. The lead must approve the actual final file and record how each disputed answer was resolved. If adjudication changes question wording or Pack scope, the fixed plan needs a new, explicitly approved version **before** any live run; this scorer will not silently reinterpret the existing questions.

## Offline command

After a valid release **and** a separately authorized, completed formal run, use:

```text
python -m scripts.score_formal_experiment --plan <frozen-plan.json> --run-dir <ignored-formal-run-dir> --final-references <human-confirmed-24.json> --reviewer-1 <completed-R1.csv> --reviewer-2 <completed-R2.csv> --adjudication <human-adjudication.json> --release <signed-freeze.json> --out-dir outputs/formal_scores/<new-name>
```

Source paths for the lock, split, test/development CSVs, original questions/references, Gold and `eval/metrics.py` default to the repository layout; they can be specified explicitly with the CLI options. The output directory must be new and under ignored `outputs/`. The scorer re-runs Stage 1 preflight and compares the entire plan. It requires the final reference hash in the release. The current candidate plan therefore fails before any report is created.

## Scoring and integrity rules

- Main accuracy uses the plan's frozen `strict` or `bounded_aliases_v1` rubric through the existing `eval.metrics.score_answer`. The additional bounded-alias result, when shown, is **diagnostic only** and never replaces strict accuracy.
- P01's Rate question targets Price. The locked `score_answer` implementation assumes Service for Rate, so the scorer maps **only that question's fixed target category** to the scorer's Service slot. It still checks the exact metric, value, numerator, denominator and explanation under the unchanged rubric. A Service claim cannot satisfy a Price question.
- Every method has a denominator of 24; each of six task types has a denominator of four. Missing, failed, partial and wrongly refused answers remain incorrect in those denominators. A correct `insufficient_info` answer is a valid refusal; a refusal to an answerable question is separately marked `false_refusal`. `COMPLETE` means 72 slots have recorded outcomes, not that all were correct.
- Result rows must match ordered task IDs, Pack/question/method IDs, the raw review source fingerprint, the shared B/C extraction hash and task-event artifact hashes. The scorer checks the 76 task events, 72 planned answer slots, request counts, output status, final recorded model response for successful answers, and method-level Token usage. Missing slots in an interrupted run appear explicitly as `missing` in the paired report.
- The call ledger is checked as begin/end pairs with request/response hashes, model identity, ordered task context, actual request count and the 504 request ceiling. Shared ABSA extraction is reported once in its own group; A, B and C each have separate call totals. Input/output Tokens, latency and estimated cost are recomputed from the call ledger and compared with the Runner summary. An unpaired request, transport error or unknown usage is reported as an anomaly; unavailable quantities remain `null`, not zero. Costs are estimates from the frozen plan's rates, not provider invoices.
- A complete, consistent `LIVE` run with frozen human references can be labelled `FORMAL_SCORE`. An incomplete live run is `INCOMPLETE_RUN_DIAGNOSTIC`. An injected offline run is always `SYNTHETIC_DIAGNOSTIC`, regardless of how many answer slots it fills. The code cannot prove the semantic quality or independence of human decisions merely from signed files; the lead must verify that provenance.

The output is `summary.json`, `per_answer.csv` (72 rows), `paired_questions.csv` (24 rows) and `summary.md`. These files can contain restricted identifiers and derived answers; keep them local. The Markdown table shows numerators and denominators. With only four questions per type, results are descriptive and should not be presented as precise population estimates.

## Stage 4 checks

After real human reviews, verify adjudication decisions against the final reference file and frozen question wording; verify current provider prices and the separately authorized live run; independently inspect a sample of request/answer traces and evidence quotes; reconcile provider billing with estimated costs; then run the read-only scorer. Evidence relevance still needs human judgment. No challenge or final-paper conclusions are produced by this Stage 3 code alone.
