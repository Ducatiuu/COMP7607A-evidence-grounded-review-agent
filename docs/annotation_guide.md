# Human annotation and review guide (blank protocol)

This document specifies work for human reviewers; no human labels or adjudication have been supplied or simulated here.

## Candidate question and reference review

Two team members independently inspect every candidate wording, pack ID, answerability, denominator, expected fields and gold-derived reference. They record proposed edits before seeing A/B/C outputs. A third reviewer resolves disagreements. Only after review should an authorized maintainer freeze question/reference manifests and hashes. Neither a model-generated wording nor an automated test counts as human approval.

## Contrastive challenge pairs

Create 40 pairs of short restaurant reviews, with one controlled sentiment/category change per pair and other aspect statements held stable. Two annotators label each pair independently: categories before/after, intended change, stable aspects, and any ambiguity. A third person adjudicates disagreements. Record original wording and revision history. Keep challenge candidates separate from SemEval and main evaluation; do not mark generated suggestions as human-written final items.

## Evidence review

Preselect 30 questions across packs and task types before seeing outcomes. Blind the method name for each A/B/C response. The packet exporter rejects recognizable method, workflow and tool names in reviewer-visible answer fields, including citation quotes. This conservative check may flag genuine source text and cannot detect indirect identity clues; inspect every packet manually before reviewers see it. Record any blinding decision separately, preserve the original run ledger, and do not silently rewrite model answers or cited evidence. Keep the private method mapping separate. Two reviewers independently break answers into short numeric and opinion claims. For numeric claims check the independent gold aggregate and denominator; for opinion claims inspect the original source text. A quoted example cannot by itself prove an aggregate. Mark supported / unsupported / unclear, citation validity and request completion separately. Preserve both raw judgments, adjudication and the chosen unit for Cohen's kappa when appropriate. Automated quote checks are only structural.

Blank CSV headers for local review sheets (no labels supplied):

```csv
pair_id,annotator_id,version,category_before,sentiment_before,category_after,sentiment_after,intended_change,stable_aspects,ambiguity_note,reviewed_at
```

```csv
question_id,blind_answer_id,annotator_id,claim_id,claim_type,claim_text,support_label,citation_validity,request_completion,rationale,reviewed_at
```

Store completed sheets under ignored `data/challenge/` or another access-controlled local path; do not publish reviewers' names, raw licensed review text or formal gold by default.

After two independent challenge sheets and third-person adjudication, build a separate local JSON reference file under ignored `data/gold/`. Each pair needs `pair_id`, `source_gold` and `edited_gold` (record IDs plus category/sentiment labels), `intended_change_categories`, `stable_categories`, subgroup tags (`negation`, `contrast`, `implicit_aspect`, or `within_aspect_conflict`), two distinct pseudonymous `independent_reviewer_ids`, a different `adjudicator_id`, and the SHA-256 of the retained adjudication record. Set `provenance` to `HUMAN_ADJUDICATED` only for actual human work. `scripts.score_challenge` consumes this file separately from extraction predictions; MOCK predictions cannot be reported as human-adjudicated live results. Synthetic software tests use `SYNTHETIC_TEST_ONLY` with no reviewer metadata.
