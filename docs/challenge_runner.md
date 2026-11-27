# Independent 40-pair Challenge run

This experiment is separate from the 24-question Method A/B/C comparison. The 40 A/B texts were drafted by Codex, reviewed and finalized by the project owner, independently labeled by two group members, and adjudicated by the owner. The local-only `data/gold/challenge_40_2026-11-27/release.json` binds the final text, both original reviewer submissions, adjudication, references, and scorer code by SHA-256. CH018 has no stable *aspect category*; CH023 retains the shared primary Food/Service labels with an ambiguity note.

`scripts.run_challenge_experiment` checks the frozen release and both reviewer sheets before execution. Its model requests contain only each sentence's ID and text, the fixed `extract-v2` prompt, and extraction configuration. Gold and references are read by preflight and the separate offline scorer, never passed to the model loop. A dry preflight is the default and does not require an API key.

## Local run protocol

Work from the project root. Create a **new** plan and run directory. Check the current model price on the [official DeepSeek pricing page](https://api-docs.deepseek.com/quick_start/pricing/) and replace the example date and values with those verified for the run. `max_requests=160` allows at most one validation retry per 80 sentences; it is a ceiling, not an expected call count. The plan builder rejects a budget below the declared worst case.

```powershell
.\.venv\Scripts\python -m scripts.plan_challenge_experiment `
  --run-dir outputs/challenge_runs/NEW_RUN_ID `
  --out outputs/challenge_plans/NEW_RUN_ID.json `
  --max-cost-usd 3.00 `
  --input-usd-per-million 0.3 `
  --output-usd-per-million 1.2 `
  --price-source 'https://api-docs.deepseek.com/quick_start/pricing/ (checked YYYY-MM-DD)' `
  --price-date YYYY-MM-DD

.\.venv\Scripts\python -m scripts.run_challenge_experiment --plan outputs/challenge_plans/NEW_RUN_ID.json
```

The first command writes a hash-bound plan without network use. The second rechecks the material and returns `PREFLIGHT_ONLY`. For a separately authorized live run, set the DeepSeek key in the local user environment, confirm the read-only balance gate, and pass the exact plan hash printed by preflight:

```powershell
.\.venv\Scripts\python -m scripts.run_challenge_experiment `
  --plan outputs/challenge_plans/NEW_RUN_ID.json `
  --execute --authorize-challenge-live --plan-sha256 EXACT_PLAN_SHA256
```

Each request has durable begin/end entries in `calls.jsonl`, and each sentence has a task journal and extraction artifact. On interruption, `--resume` is allowed only after all preceding requests have known outcomes and all completed artifacts and hashes match. Unknown or in-flight requests stop automatic recovery. All failed extractions stay in the pair denominator.

Once `summary.json` reports `COMPLETE`, audit the 80 record artifacts, 40 pair predictions, request ledger, evidence substrings, usage, and hash chain. Then score offline, passing all 40 pair files to the separate frozen Gold scorer:

```powershell
$predictionFiles = @(Get-ChildItem -LiteralPath 'outputs/challenge_runs/NEW_RUN_ID/predictions' -Filter 'CH*.json' | Sort-Object Name | ForEach-Object FullName)
.\.venv\Scripts\python -m scripts.score_challenge `
  --predictions $predictionFiles `
  --references data/gold/challenge_40_2026-11-27/references.json `
  --out outputs/challenge_scores/NEW_RUN_ID/score.json
```

The scorer rejects MOCK predictions against human-adjudicated references. Do not edit the frozen Gold, scorer, text or Prompt after seeing results.

## Completed local run (2026-11-27)

The ignored local run `outputs/challenge_runs/challenge_40_v1_2026-11-27/` completed 80/80 extractions and 40/40 pairs with 81 requests, including one successful validation retry. Recorded usage was 25,832 input and 4,818 output tokens; the frozen price estimate was USD 0.0135312. The independent score under `outputs/challenge_scores/challenge_40_v1_2026-11-27/` is 34/40 intended changes, 39/39 stable categories, and 34/40 passing pairs. The four ten-pair subgroup rates are negation 10/10, contrast 8/10, implicit aspect 7/10, and within-aspect conflict 9/10. The six failed pair IDs are CH014, CH020, CH025, CH027, CH029 and CH039; all failed on the edited sentence's target sentiment. The local `REPORT_ZH.md` and per-pair diagnostic retain the audit and source hashes. These generated, human-reviewed sentences are a small Challenge set and should not be described as human-authored or combined with the A/B/C question-answer accuracy.

The raw text, reviewer labels, Gold, model calls and score artifacts are Git ignored and must not be uploaded to the public repository.
