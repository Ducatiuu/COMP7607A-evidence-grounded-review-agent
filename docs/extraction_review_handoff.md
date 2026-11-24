# 13-record development extraction review handoff

This review concerns **development data only**. The source CSV and JSON live in the ignored local directory `outputs/extraction_review_v8_2026-11-24/`; do not put them in a public repository. The source sheet is a record of the agent's provisional triage, not a human judgment. Its `review_sheet.json` SHA-256 is `813cfd340154a473ce77d2a75f9cb300d20424ce65dd7b89fea42968d9f6c194`.

Two separate blank files, `reviewer_1.csv` and `reviewer_2.csv`, are ready for group members. They omit the agent's provisional classification and reason so each reviewer can judge independently. Each contains the same 13 original texts, Gold labels, model labels, and mechanically identified differences. They have no filled human decisions.

For every row, fill `human_decision`; the browser fills `reviewer` and `reviewed_at`. `human_reason` may remain blank only for `no_issue`. Use one of these exact decision values:

| Value | Meaning |
| --- | --- |
| `model_error` | The source text and task annotation rules support the Gold label; the model's differing label is unsupported. |
| `annotation_ambiguity` | The source text reasonably supports both readings or the Gold label itself needs adjudication. |
| `both_or_mixed` | The row contains multiple differences with different causes. Explain each in `human_reason`. |
| `false_discrepancy` | The reported difference does not exist in the matching Gold and prediction; identify the comparison or record-alignment mistake. Older CSV drafts using `no_error` are converted on import. |
| `no_issue` | The listed difference is real, but both label interpretations are acceptable under the annotation rules and no further ruling is needed. A reason is optional. |
| `unresolved` | The reviewer cannot decide from the text and annotation guidelines. State what is missing. |

Use the original sentence and SemEval annotation guidelines linked from the [official task page](https://alt.qcri.org/semeval2014/task4/index.php?id=data-and-tools), especially for neutral facts, overall experience (`anecdotes/miscellaneous`), and cross-aspect sentiment. Do not assume that either Gold or the model is always right. Record a short source-based reason; avoid changing `record_id`, `review_text`, `gold_aspects`, `predicted_aspects`, or `differences`. Use a reviewer identifier rather than private contact information. Keep the two files separate until both reviewers finish. Any disagreements should be discussed and recorded as a separate adjudication, not silently overwritten in either reviewer's sheet.

The 120 formal question/reference reviews are a **different** task, with their own two blank sheets under `data/gold/question_review/0ba746858bfd/`. Completing this 13-record development diagnostic does not freeze the formal test set or supply formal human evidence scores.
