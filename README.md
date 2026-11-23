# Evidence-Grounded ABSA Agent

Local development of an English restaurant review analysis system for COMP7607A. The current offline build has typed records, CSV loading, bounded extraction with a versioned cache, four deterministic tools, A/B/C controllers, local SemEval preparation code, offline metrics and a synthetic Streamlit demo. A tested OpenAI/DeepSeek Responses transport is available behind the shared model interface. Licensed Train V2.0, Phase B input and Gold test XML have been locally audited; real candidate splits and questions exist under ignored paths. A separately approved `direct-v2` retest passed on four synthetic reviews. The first approved real-data Pilot stopped at extraction validation: 9 of 30 records passed the structural check, 21 failed, and no A/B/C question was run. A three-record `extract-v1` probe identified a repeated `evidence` list-type error; `extract-v2` fixed structural coverage on a three-record retest. The v4 30-record/10-question development Pilot completed 30 extractions and 30 method results, but 20/20 B/C question parses failed schema validation. A one-question probe identified an invalid `metric` value and an extra field. Versioned `query-v2` now gives the allowed fields and values. A separate one-question development retest passed query parsing and two analysis tools, then failed final-answer verification after one repair. A bounded follow-up found missing required answer fields and extra keys on both answer attempts. Versioned `answer-v2` fixed the schema on one development question, but the generated number failed grounding on both attempts. Versioned `answer-v3` supplies candidate numeric claims copied from trusted analysis tools and passed a one-question B retest. A one-question C probe exposed an incomplete dynamic tool sequence; versioned `decision-v2` now states its required evidence and awaits a small live retest. Human review, formal freeze and research results remain pending.

## Set up

Python 3.12 is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev,ui]'
.\.venv\Scripts\python -m pytest -q
```

The `MockLLMClient` is for offline tests only. The original Proposal has now been reviewed; see [proposal alignment](docs/proposal_alignment.md), `docs/TASKS.md` and `docs/PROGRESS.md` for commitments, gaps and actual verification status.

## Provider transport status

`src.responses_client.ResponsesClient` implements the shared `LLMClient` contract for the official OpenAI and DeepSeek Responses endpoints. It reads `OPENAI_API_KEY` or `DEEPSEEK_API_KEY` only when called with `allow_network=True`, sends one request without hidden retries, caps output tokens and timeout, and rejects incomplete/refused/non-JSON responses. OpenAI requests set `store=false`; DeepSeek requests set `reasoning.effort=none` to use the documented non-thinking mode for bounded JSON calls. DeepSeek's Responses API is stateless. JSON mode supplies syntax only; the existing Pydantic and source-evidence checks still validate the returned object. The transport passed local simulated-HTTP tests. A `direct-v2` live retest returned a valid answer on four synthetic reviews. The separate `src.live_cli` has a balance-gated live CSV path; the development Pilot runner has now run on real Train-derived data and retained failed B/C query parses. The Streamlit UI and formal experiment remain MOCK-only. [OpenAI Responses reference](https://developers.openai.com/api/reference/resources/responses/methods/create); [DeepSeek Responses guide](https://api-docs.deepseek.com/guides/responses_api/); [DeepSeek thinking-mode controls](https://api-docs.deepseek.com/guides/thinking_mode/).

For a new DeepSeek key on Windows, run `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\configure_deepseek.ps1` locally. The script prompts without echoing the key, checks the read-only official `/models` endpoint, and saves `DEEPSEEK_API_KEY` as a user environment variable only after authentication succeeds. Restart Codex so its processes inherit the new variable. Never paste a key into chat or commit it to the repository. This check does not send review data or run model inference. A failed check leaves any existing user key unchanged.

For the user's 2026-11-23 standing authorization, bounded DeepSeek development runs no longer need a separate chat approval. `src.deepseek_balance` queries the official read-only `/user/balance` endpoint before live execution and permits a new run only if its configured cap fits within a conservative allowance that reserves at least half the account balance. The CNY safety divisor is deliberately conservative and is not presented as a market exchange rate. An unavailable, malformed or insufficient balance stops the run before any review is sent. Request, token and cost guards and unique run directories still apply. Formal holdout, another provider, public release and human review are outside this automatic authorization.

## Review CSV contract

The loader accepts UTF-8 CSV with a nonblank review text column. `load_csv(path, text_column="review", id_column="row_id")` maps other header names explicitly. If the ID column is absent, each row receives a deterministic `auto-...` ID based on its position and text; identical review text on separate rows remains separate. An explicitly supplied ID column must be complete and unique. Extra CSV columns are accepted but are not currently used for analysis, so questions needing date, rating or customer identity cannot be answered from them yet. Empty reviews, missing fields, duplicate IDs, malformed rows and empty files are rejected rather than silently skipped.

`src.live_runtime.run_model_method` connects any validated review `RecordSet` to A/B/C through an injected model client. The caller must supply record-count, input-character and conservative request ceilings before a model call. B/C can share a validated extraction dataset; A reads only raw reviews. The runtime counts attempted requests and known tokens across extraction and answering, including failed attempts. The character limit is a source-size guard, not a guaranteed provider token or fee cap. This path has passed injected-model tests and is exposed through the separate gated live CLI. The v4 real-data development Pilot exercised all 30 method-question rows, but B/C query parsing failed on every question; that behavior is preserved as a development failure, not validation success.

`src.live_cost.plan_cost` additionally requires a dated price source, non-cached input/output rates, per-request token bounds and a USD cap. It refuses a declared worst-case plan above the cap. `CostLimitedClient` freezes further network requests if transport fails or measured tokens are missing/out of bounds. Its USD figure is an estimate from supplied rates, not a provider bill; an unexpectedly large first response or stale/incorrect prices can still violate the planned bound. No price or live-spend approval is embedded in this repository.

`python -m src.live_cli ask --help` and `python -m src.live_cli extract --help` expose the model-backed CSV path. Both commands run a local `DRY_RUN` by default and require the file, column mapping if needed, provider/model, record/character/request/token ceilings, dated input/output prices and a USD cap. `--execute` explicitly enables network use and reads the matching key from the environment; the standing DeepSeek development authorization applies when the exact model, data scope, current prices, balance and per-run limits are checked. Other providers and formal holdout still need separate authorization. Failed/partial extraction and failed answers return a nonzero exit status. The CLI does not use demo answers or formal gold labels. The Streamlit UI and experiment runner remain MOCK-only.

`python -m scripts.prepare_dev_pilot` prepares a local, unreviewed candidate for a development pilot. It selects 30 records from `data/processed/dev.csv` with a fixed seed, writes ten questions and a runtime CSV under ignored `data/processed/dev_pilot/`, and keeps the independent Gold references under ignored `data/gold/dev_pilot/`. It never calls a model or reads formal test records. The generated manifest records source and output hashes; existing files are not overwritten. Any new live development plan uses the standing DeepSeek balance gate and leaves this candidate marked unreviewed.

`python -m scripts.plan_dev_pilot --help` exposes a read-only preflight for that candidate. It checks hashes, dev/test ID separation, an unused run directory and a conservative full A/B/C request plan. The one-shot runner has an offline test of shared extraction, all 30 A/B/C answers, a durable call ledger, and failure stops. Its live mode requires both `--execute` and the exact plan SHA-256 via `--approved-plan-sha256`; this flag binds configuration and is not a request for repeated chat approval under the standing DeepSeek dev authorization. The v3 and v4 runs each used separate non-reusable directories. V3 stopped at extraction coverage; v4 completed all result rows but failed its quality checks because B/C query parses were invalid. The extraction service and query parser now expose redacted structural diagnostics. Reference-based Pilot scoring remains pending.

The three-record `extract-v1` probe stopped after six requests. Every response failed the same structural rule: `evidence` must be a JSON list. The saved result remains under ignored `outputs/live_probe/`. `extract-v2` gives an explicit JSON example and requires a list of exact review substrings. The live CSV CLI defaults to v2 and records the prompt version in its preflight; the mock evaluation retains v1 provenance. The v2 retest succeeded structurally on all three records in three requests. V4 then achieved 30/30 structural extraction coverage, although semantic and downstream answer failures remain.

`python -m scripts.audit_question_review` checks the two local 120-question review sheets for missing judgments, changed source fields, reported reviewer IDs and disagreements. It never supplies human judgments or freezes the formal question set.

## Offline CLI (synthetic fixture)

The CLI accepts the unchanged four illustrative records from the Proposal or a separate, clearly simulated 60-entry presentation fixture, and only the two exact questions below. `MOCK` in every output means the model responses are predefined test data; it does not measure model accuracy.

```powershell
.\.venv\Scripts\python -m src.cli extract --input data/demo/core.csv --mock
.\.venv\Scripts\python -m src.cli ask --method a --input data/demo/core.csv --question "What is the negative service rate?" --mock
.\.venv\Scripts\python -m src.cli ask --method b --input data/demo/core.csv --question "What is the negative service rate?" --mock
.\.venv\Scripts\python -m src.cli ask --method c --input data/demo/core.csv --question "What is the negative service rate?" --mock
.\.venv\Scripts\python -m src.cli ask --method b --input data/demo/core.csv --question "Did negative service reviews improve over the last month?" --mock
.\.venv\Scripts\python -m src.cli ask --method c --input data/demo/presentation.csv --question "What is the negative service rate?" --mock
```

For the four-record example, service is 2 negative records (R01/R04) / 3 mentions (R01/R03/R04) = 2/3. For the 60-entry fixture, it is 24/48 = 1/2. The date question returns `insufficient_info` because dates are absent. Method A receives all raw entries and the question; Method B uses the extracted fixture, shared query parse, deterministic aggregate, shared answer generation and output checks. Method C uses the same extraction, parser, tools and finalizer, but a bounded mock decision loop chooses its tool calls after seeing results. Arbitrary questions, other uploaded datasets and live API execution are not configured in this CLI.

## Offline run ledger

```powershell
.\.venv\Scripts\python -m eval.run_method --method b --split demo --mock
.\.venv\Scripts\python -m eval.run_method --method c --split demo --condition repeats --mock
```

Rows are append-only under ignored `outputs/runs/`; a matching rerun skips completed tasks. Explicit `--retry-failed` appends one more attempt for a failed/partial task. The report scores the latest attempt per task while counting requests, cost and measured wall time from all retained attempts. It separates query time after extraction from full attempt time and any measured extraction time. Configuration and full task payload hashes block accidental mixing. Each actual MOCK model request also appends a stage/timing/usage row to local `model_calls.jsonl`; unknown tokens and cost remain null. The synthetic demo also exercises B/C `gold`, C `ablation`, and a separate extraction-only challenge. Formal dev/test and live provider runs remain pending. See [experiment preparation](docs/experiment_plan.md) and [data handling](docs/data_sources.md).

With a request cap, the runner stops further tasks immediately if an attempt reports unknown usage or more calls than its declared upper bound; the attempt remains in the ledger for review.
The optional MOCK cost cap uses recorded known fees plus the next task's conservative estimate. Unknown or over-bound fee stops further tasks and leaves cost unknown; no real provider pricing is configured.

For a fairer B/C offline path, `scripts.prepare_shared_extraction --mock` saves one hash-bound synthetic extraction under ignored `outputs/`; pass that directory as `--shared-extraction` to both `eval.run_method` calls. The setup request count remains separate and is counted once across the comparison.
Pass the same `--shared-extraction` directory to `scripts.summarize_runs` to validate both bindings and report the combined physical B/C request count; unknown cost stays null.

## Local Streamlit demo

```powershell
.\.venv\Scripts\python -m streamlit run app.py
```

The server binds to `127.0.0.1`. Load the four-record Proposal example or the 60-entry simulated fixture, run MOCK extraction, inspect the highest negative count and source records, select food-positive AND service-negative records, ask the displayed rate or missing-date question with A/B/C, then compare methods and traces. The 60-entry fixture is generated reproducibly with `python -m scripts.build_presentation_demo`; see the [four-minute walkthrough](docs/demo_script.md). Browser refresh restores locally saved state through a random URL token; **Clear local workspace** removes that saved state. Uploads are capped at 1 MB for CSV and 5 MB for extraction JSON. A different CSV can be paired with a separately validated `ExtractionDataset` JSON for deterministic charts/evidence; canned MOCK questions are unavailable for it. No live API or formal result is shown.

The local development plan is in `CODEX-v2.5.md`; repository constraints are in `AGENTS-v2.5.md`. Licensed raw data, formal gold labels, credentials, and local run outputs are ignored by Git. Synthetic demo gold/reference fixtures are tracked as test data.
