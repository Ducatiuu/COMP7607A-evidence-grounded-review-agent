# Evidence-Grounded ABSA Agent

Local development of an English restaurant review analysis system for COMP7607A. The current offline build has typed records, CSV loading, bounded extraction with a versioned cache, four deterministic tools, A/B/C controllers, local SemEval preparation code, offline metrics and a synthetic Streamlit demo. Formal data, human review, live API integration and research results remain pending.

## Set up

Python 3.12 is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev,ui]'
.\.venv\Scripts\python -m pytest -q
```

The `MockLLMClient` is for offline tests only. No live provider or real experiment is configured. The original Proposal has now been reviewed; see [proposal alignment](docs/proposal_alignment.md), `docs/TASKS.md` and `docs/PROGRESS.md` for commitments, gaps and actual verification status.

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
