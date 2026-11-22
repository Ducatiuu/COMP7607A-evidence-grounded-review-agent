# Evidence-Grounded ABSA Agent

Local development of an English restaurant review analysis system for COMP7607A. The current offline build has typed records, CSV loading, bounded extraction with a versioned cache, four deterministic tools, A/B/C controllers, local SemEval preparation code, offline metrics and a synthetic Streamlit demo. Formal data, human review, live API integration and research results remain pending.

## Set up

Python 3.12 is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev,ui]'
.\.venv\Scripts\python -m pytest -q
```

The `MockLLMClient` is for offline tests only. No live provider or real experiment is configured. The original proposal is absent from the supplied directory, so its research commitments have not yet been independently checked. See `docs/TASKS.md` and `docs/PROGRESS.md` for actual implementation and verification status.

## Offline CLI (synthetic fixture)

The current CLI fixture accepts only the unchanged `data/demo/core.csv` and the exact question below. `MOCK` in every output means the model responses are predefined test data; it does not measure model accuracy.

```powershell
.\.venv\Scripts\python -m src.cli extract --input data/demo/core.csv --mock
.\.venv\Scripts\python -m src.cli ask --method a --input data/demo/core.csv --question "What is the negative service rate?" --mock
.\.venv\Scripts\python -m src.cli ask --method b --input data/demo/core.csv --question "What is the negative service rate?" --mock
.\.venv\Scripts\python -m src.cli ask --method c --input data/demo/core.csv --question "What is the negative service rate?" --mock
```

Expected service result: 2 negative records / 3 records mentioning service = 2/3. Method A receives only all four raw reviews and the question; Method B uses the extracted fixture, shared query parse, deterministic aggregate, shared answer generation and output checks. Method C uses the same extraction, parser, tools and finalizer, but a bounded mock decision loop chooses its tool calls after seeing results. Arbitrary questions, uploaded datasets and live API execution are not yet configured in this CLI.

## Offline run ledger

```powershell
.\.venv\Scripts\python -m eval.run_method --method b --split demo --mock
.\.venv\Scripts\python -m eval.run_method --method c --split demo --condition repeats --mock
```

Rows are append-only under ignored `outputs/runs/`; a matching rerun skips completed tasks. Explicit `--retry-failed` appends one more attempt for a failed/partial task. Configuration and full task payload hashes block accidental mixing. The synthetic demo also exercises B/C `gold`, C `ablation`, and a separate extraction-only challenge. Formal dev/test and live provider runs remain pending. See [experiment preparation](docs/experiment_plan.md) and [data handling](docs/data_sources.md).

## Local Streamlit demo

```powershell
.\.venv\Scripts\python -m streamlit run app.py
```

The server binds to `127.0.0.1`. Load the synthetic demo (or upload the unchanged `data/demo/core.csv`), run MOCK extraction, inspect aspect counts and evidence, ask the displayed question with A/B/C, then compare methods and traces. Browser refresh restores locally saved state through a random URL token; **Clear local workspace** removes that saved state. Uploads are capped at 1 MB for CSV and 5 MB for extraction JSON. A different CSV can be paired with a separately validated `ExtractionDataset` JSON for deterministic charts/evidence; the canned MOCK question is deliberately unavailable for it. No live API or formal result is shown.

The local development plan is in `CODEX-v2.5.md`; repository constraints are in `AGENTS-v2.5.md`. Licensed raw data, formal gold labels, credentials, and local run outputs are ignored by Git. Synthetic demo gold/reference fixtures are tracked as test data.
