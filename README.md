# Evidence-Grounded ABSA Agent

Local development of an English restaurant review analysis system for COMP7607A. The current offline build has typed records, CSV loading, bounded extraction with a versioned cache, four deterministic tools, a shared structured query parser and A/B/C controllers. Evaluation and UI are subsequent phases.

## Set up

Python 3.12 is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev]'
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

The local development plan is in `CODEX-v2.5.md`; repository constraints are in `AGENTS-v2.5.md`. Raw data, gold labels, credentials, and local run outputs are ignored by Git.
