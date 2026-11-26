# Formal freeze: Stage 4 offline acceptance

The owner confirmed the final four-Pack question and reference decisions. The original candidate lock, both independent review sheets, Gold and the 120-question source remain unchanged. A new local version holds the selected final wording, adjudication, release manifest and plan under ignored `outputs/formal_freeze_release_2026-11-27/`. One Method A exploratory call had already used the first Pack with a discarded alternative question. That result is excluded from formal scoring, and the prior Pack exposure must be disclosed in the report.

The version 2 lock binds the original candidate lock and reviewer sheets, the owner decision records, the final 24-question subset, all source files, the scoring code, and each Prompt source file by SHA-256. The `FROZEN` release binds that lock, the adjudication and the human-confirmed 24-reference file. `scripts.plan_final_formal_experiment` reconstructs these checks from disk. Stage 2 `checked_plan` dispatches to this versioned preflight; Stage 3 requires the same release and final reference hash. Changing an execution flag or a single manifest field cannot make an altered version pass.

Run the offline preflight from the project root with the local configuration:

```powershell
.\.venv\Scripts\python.exe -m scripts.plan_final_formal_experiment --config outputs\formal_freeze_release_2026-11-27\preflight_config.json --out outputs\formal_freeze_release_2026-11-27\another_unused_plan.json
```

The command performs no provider request and refuses to overwrite an output plan. A successful plan reports `FROZEN_PREFLIGHT_READY`, `material_state=FROZEN`, `execution_permitted=false` and `network_calls_made=0`. A separate live-run authorization and exact plan hash are still required by the Runner. The present plan uses historical development pricing assumptions; the live CLI rejects such a source even with an authorization flag. Before any later formal call, verify current official DeepSeek prices, set a fresh request/token/budget plan, inspect the account balance under the existing gate, and obtain separate human authorization. Do not reuse the exploratory diagnostic as a formal A/B/C result.

Synthetic tests exercise the final version through preflight, a 72-answer A/B/C batch, shared extraction, pause/resume, an uncertain transport failure, complete logs and independent offline scoring. Synthetic fixture approvals do not represent actual reviewer judgments. The real formal 24-question model run and formal scoring have not been performed. All restricted review, Gold, release and run files remain local and Git ignored.
