# Development progress

## 2026-11-22: initial state

- Input inventory: only `AGENTS-v2.5.md` and `CODEX-v2.5.md`. No Proposal, data, code, tests, or Git repository existed.
- Authorization interpreted as local autonomous development. Public GitHub creation/sync, real API use, formal holdout runs, and human labels are not authorized by this request.
- Phase 0 began with package, task ledger, typed schemas, offline client and framework survey. Module gates remain open until review and real test results are recorded.

## P0-SCHEMA — PASS (offline)

- Files: `src/schemas/models.py`, `src/schemas/__init__.py`, `src/llm_client.py`, `tests/test_schemas.py`, `tests/test_llm_client.py`, `docs/data_contract.md`.
- Self-review: reread typed boundaries and negative tests. Found that failed extraction accepted whitespace-only errors and record IDs; tightened both validators and reran tests. The dataset validates exact evidence substrings and ID/coverage alignment; it does not judge semantic support.
- Functional check: `.venv/Scripts/python -m pytest -q tests/test_schemas.py tests/test_llm_client.py` exited 0: 9 passed, 0 failed, 0 skipped. Independent smoke: missing ID for `"  Nice food  "` became `auto-9bc1b0e6b90bf41d` while original text remained unchanged; offline config reported `mock`.
- All model answers were explicit fixtures. Real ABSA/model behavior remains untested and requires provider/model/data/budget approval.

## P0-SETUP — PASS (local)

- Files: `.gitignore`, `pyproject.toml`, `requirements.lock.txt`, `.env.example`, `README.md`, `src/config.py`, `docs/framework_survey.md`, `docs/TASKS.md`, `docs/PROGRESS.md`.
- Python 3.12.10 venv install via `python -m pip install -e '.[dev]'` exited 0; Pydantic 2.14.4 and pytest 9.2.0 installed. Import and smoke command exited 0. `git init -b main` created a local repository; no remote was created or contacted for synchronization. Ignored status verified for `.venv/`, `.codex-local/`, package metadata and Python caches.
- Survey read GitHub API metadata, root entries and default branch HEAD on 2026-11-22. No code copied. Missing Proposal blocks independent verification of the original research commitments, but not the local Phase 0 implementation.
- Self-review: checked packaging, ignored local/sensitive paths, documented limitations and omitted an unverified upstream directory claim. No known Phase 0 acceptance issue remains.
- Next: P1-LOAD, then P1-EXTRACT. GitHub synchronization remains NOT AUTHORIZED.

## P1-LOAD — PASS (offline)

- Files: `src/data_loader.py`, `data/demo/core.csv`, `tests/test_data_loader.py`, `docs/data_contract.md`.
- Self-review: checked text preservation, generated IDs, duplicate detection, malformed rows and fingerprint stability. The first test run exposed that `csv.DictReader` silently skips an empty physical row (`text\n\n`); added a line-aware guard that still allows blank lines inside quoted review text.
- Initial test command `.venv/Scripts/python -m pytest -q tests/test_data_loader.py tests/test_schemas.py tests/test_llm_client.py` exited 1: 1 failed, 17 passed. After fix and a quoted multiline regression test, same command exited 0: 19 passed, 0 failed, 0 skipped.
- Expected/actual: demo IDs R01–R04 and R01 original sentence matched exactly; repeated load produced identical fingerprint. Blank standalone row now raises `DataLoadError`; quoted multiline review retains its embedded blank line.
- All fixture reviews are synthetic. No SemEval or user data was loaded. Next: P1-EXTRACT.

## P1-EXTRACT — PASS (offline)

- Files: `src/absa_service/extractor.py`, `src/absa_service/__init__.py`, `tests/test_extraction_validation.py`, `tests/test_cache.py`, `docs/data_contract.md`.
- Self-review: checked retry boundaries, model/ID alignment, duplicate categories, exact spans, failed status and cache key material. Found that cache deserialization could raise on a wrong JSON type and that a response from a different actual model could be cached under the configured model; fixed both and added a mismatch regression test.
- Functional check after correction: `.venv/Scripts/python -m pytest -q tests/test_extraction_validation.py tests/test_cache.py tests/test_data_loader.py tests/test_schemas.py tests/test_llm_client.py` exited 0: 27 passed, 0 failed, 0 skipped. Test fixtures checked a bad quote followed by a valid retry, persistent failure with retained ID/coverage, duplicate aspect, invalid sentiment, mismatched model, same text with a new ID, changed model/prompt/schema/config cache misses and corrupt cache recomputation.
- Expected/actual: invalid first span required 2 requests and 1 retry, valid second span accepted; persistent failure retained `failed_ids=["R1"]`; cache hit under a second ID made 0 requests and yielded the second ID. No live model calls. The mock validates control flow and contracts, not ABSA accuracy.
- Phase 1 offline gate: PASS for loader and extraction modules; full phase focused suite had 27 passes. Next: four tools and shared parser in Phase 2.

## P2-FILTER — PASS (offline)

- Files: `src/tools/analysis.py`, `src/tools/__init__.py`, `tests/test_tools.py`.
- Self-review: checked record-level AND/OR, stable order, duplicate/unknown scope rejection and failed-extraction handling. Clarified the conditional expression during review.
- Functional check: `.venv/Scripts/python -m pytest -q` exited 0 with 38 passed, 0 failed, 0 skipped. The filter test expected and obtained R01 for food-positive AND service-negative, and R01/R02/R03 for OR. A failed extraction makes status `partial` rather than pretending no match.

## P2-AGG — PASS (offline)

- Files and command: same tools module and full suite as above. Self-review checked distinct record count, category uniqueness, negative versus conflict and partial/all-record denominator behavior.
- Hand-calculated expectations matched actual: service mentions 3, negative 2, rate 2/3; price 1, negative 1, rate 1; ambience mentions 0 and rate null. Service negative/all-record rate was 2/4. When one extraction failed, observed mention rate remained descriptive and marked partial; full-population rate became null.

## P2-COMPARE — PASS (offline)

- Files and command: same tools module and full suite as above. Self-review checked same scope and exact numeric sorting; no display rounding determines ties. Actual mention-count comparison put service and food in one tie group (3 each); undefined ambience rate was separate.

## P2-EVIDENCE — PASS (offline)

- Files and command: same tools module and full suite as above. Self-review found evidence items were loosely typed and an empty selection was disallowed; changed to typed annotations and permitted an empty ID list, then reran the full suite. Actual result retained the full selected ID list while limiting examples to one exact original sentence/span. Unknown IDs raised an error.

## P2-PARSER — PASS (offline)

- Files: `src/controllers/query_parser.py`, `src/schemas/models.py`, `tests/test_query_parser.py`. Self-review checked single request, independent predicate pairs, model match, invalid parse, metadata availability and no tool-order output. Tightened QuerySpec coherence for rate, selection and comparison tasks.
- Functional check: `.venv/Scripts/python -m pytest -q` exited 0 with 38 passed, 0 failed, 0 skipped. Mock parser made one request, retained food-positive/service-negative as two paired conditions and marked a date-dependent query `unavailable_metadata`. No live language understanding is claimed.
- Phase 2 offline gate: PASS. `git diff --check` found no whitespace errors. Git repository is local on `main`; no remote/push authorized. Next: Phase 3 A/B, shared verification and CLI.
