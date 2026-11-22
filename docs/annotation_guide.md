# Human annotation and review guide (blank protocol)

This document specifies work for human reviewers; no human labels or adjudication have been supplied or simulated here.

## Candidate question and reference review

Two team members independently inspect every candidate wording, pack ID, answerability, denominator, expected fields and gold-derived reference. They record proposed edits before seeing A/B/C outputs. A third reviewer resolves disagreements. Only after review should an authorized maintainer freeze question/reference manifests and hashes. Neither a model-generated wording nor an automated test counts as human approval.

## Contrastive challenge pairs

Create 40 pairs of short restaurant reviews, with one controlled sentiment/category change per pair and other aspect statements held stable. Two annotators label each pair independently: categories before/after, intended change, stable aspects, and any ambiguity. A third person adjudicates disagreements. Record original wording and revision history. Keep challenge candidates separate from SemEval and main evaluation; do not mark generated suggestions as human-written final items.

## Evidence review

Preselect 30 questions across packs and task types before seeing outcomes. Blind the method name for each A/B/C response. Two reviewers independently break answers into short numeric and opinion claims. For numeric claims check the independent gold aggregate and denominator; for opinion claims inspect the original source text. A quoted example cannot by itself prove an aggregate. Mark supported / unsupported / unclear, citation validity and request completion separately. Preserve both raw judgments, adjudication and the chosen unit for Cohen's kappa when appropriate. Automated quote checks are only structural.

Blank CSV headers for local review sheets (no labels supplied):

```csv
pair_id,annotator_id,version,category_before,sentiment_before,category_after,sentiment_after,intended_change,stable_aspects,ambiguity_note,reviewed_at
```

```csv
question_id,blind_answer_id,annotator_id,claim_id,claim_type,claim_text,support_label,citation_validity,request_completion,rationale,reviewed_at
```

Store completed sheets under ignored `data/challenge/` or another access-controlled local path; do not publish reviewers' names, raw licensed review text or formal gold by default.
