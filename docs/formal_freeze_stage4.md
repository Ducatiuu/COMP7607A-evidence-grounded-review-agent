# Formal freeze: Stage 4 offline acceptance

The owner confirmed the final four-Pack question and reference decisions. The original candidate lock, both independent review sheets, Gold and the 120-question source remain unchanged. A new local version holds the selected final wording, adjudication, release manifest and plan under ignored `outputs/formal_freeze_release_2026-11-27/`. One Method A exploratory call had already used the first Pack with a discarded alternative question. That result is excluded from formal scoring, and the prior Pack exposure must be disclosed in the report.

The version 2 lock binds the original candidate lock and reviewer sheets, the owner decision records, the final 24-question subset, all source files, the scoring code, and each Prompt source file by SHA-256. The `FROZEN` release binds that lock, the adjudication and the human-confirmed 24-reference file. `scripts.plan_final_formal_experiment` reconstructs these checks from disk. Stage 2 `checked_plan` dispatches to this versioned preflight; Stage 3 requires the same release and final reference hash. Changing an execution flag or a single manifest field cannot make an altered version pass.

Run the offline preflight from the project root with the local configuration:

```powershell
.\.venv\Scripts\python.exe -m scripts.plan_final_formal_experiment --config outputs\formal_freeze_release_2026-11-27\preflight_config.json --out outputs\formal_freeze_release_2026-11-27\another_unused_plan.json
```

The command performs no provider request and refuses to overwrite an output plan. A successful plan reports `FROZEN_PREFLIGHT_READY`, `material_state=FROZEN`, `execution_permitted=false` and `network_calls_made=0`. A separate live-run authorization and exact plan hash are still required by the Runner. Do not reuse the exploratory diagnostic as a formal A/B/C result.

## P0 startup check (2026-11-27)

An additional ignored local configuration, `preflight_config_official_2026-11-27.json`, records the [official DeepSeek model/pricing page](https://api-docs.deepseek.com/quick_start/pricing/) checked on 2026-11-27. It preserves the original model, 504-request ceiling, per-request token caps, local spend cap and unused run directory; only the price source/date changed. The conservative peak price values already matched the official page. The resulting `preflight_plan_official_2026-11-27.json` has plan SHA-256 `f47eed94f6766b7be18a596c9e47fc21da040c2b10f45b71182ab41735163881`. The final-material preflight, live-price freshness check and Runner dry precheck passed without a model call. The original historical plan remains preserved.

The project owner explicitly authorized both transfer of the selected review text to DeepSeek and this frozen 24-question A/B/C live experiment. The chat-recorded authorization is kept in ignored `formal_live_authorization_2026-11-27.json`, bound to the current plan SHA-256; it is not a cryptographic signature or an independent interpretation of upstream META-SHARE terms. Gold labels and reference answers remain local. The planned run directory is unused, writable and Git ignored.

The formal CLI now uses a read-only balance check against the **declared worst-case usage** from the unchanged 504-request and per-request Token bounds. It no longer adds the development-only extra balance reserve. The development balance rule and formal request/Token/spend caps are unchanged. The current key authenticated and this formal balance check passed. The point-in-time local status is `startup_readiness_2026-11-27.json`: no startup blocker at the time of checking. The Runner still requires `--execute --authorize-formal-live --plan-sha256 <exact hash>` and rebuilds the frozen-material gate. `execution_permitted=false` in the planning artifact remains intentional and must not be edited. No formal model request has been made during this P0 check.

Synthetic tests exercise the final version through preflight, a 72-answer A/B/C batch, shared extraction, pause/resume, an uncertain transport failure, complete logs and independent offline scoring. Synthetic fixture approvals do not represent actual reviewer judgments. The real formal 24-question model run and formal scoring have not been performed. All restricted review, Gold, release and run files remain local and Git ignored.
