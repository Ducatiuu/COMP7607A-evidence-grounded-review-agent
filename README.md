# Evidence-Grounded ABSA Agent

Local development of an English restaurant review analysis system for COMP7607A. The current offline build has typed records, CSV loading, bounded extraction with a versioned cache, four deterministic tools and a shared structured query parser. A/B/C controllers, evaluation and UI are subsequent phases.

## Set up

Python 3.12 is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e '.[dev]'
.\.venv\Scripts\python -m pytest -q
```

The `MockLLMClient` is for offline tests only. No live provider or real experiment is configured. The original proposal is absent from the supplied directory, so its research commitments have not yet been independently checked. See `docs/TASKS.md` and `docs/PROGRESS.md` for actual implementation and verification status.

The local development plan is in `CODEX-v2.5.md`; repository constraints are in `AGENTS-v2.5.md`. Raw data, gold labels, credentials, and local run outputs are ignored by Git.
