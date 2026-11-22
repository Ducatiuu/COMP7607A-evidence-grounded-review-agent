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

## Local checkpoint after Phase 2

- Inspected staged paths for generated/sensitive content and made local commit `bd8617caa56fcd0b22a255f3d772fa3dcc90fc1d` on `main`. No Git remote exists; synchronization status remains NOT AUTHORIZED.

## P3-DISPATCH — PASS (offline)

- Files: `src/tools/dispatcher.py`, `src/tools/__init__.py`, `tests/test_dispatcher.py`; `src/tools/analysis.py` gained distinct record count and explicit comparison denominator fields.
- Self-review: only four named pure functions are reachable; Pydantic validates arguments before calling; unknown tool and invalid scope produce failed `ToolResult` with no code execution. Comparison denominator omission surfaced in a later verifier test and was fixed.
- Tests: focused `tests/test_dispatcher.py tests/test_tools.py` exited 0: 8 passed. Full suite after Phase 3 exited 0: 53 passed, 0 failed, 0 skipped.

## P3-VERIFY — PASS (offline)

- Files: `src/verification/output_checks.py`, `src/verification/repair.py`, `src/schemas/models.py`, `tests/test_output_checks.py`.
- Self-review: checked tool-backed numbers and scope, denominator type, citation ID and exact source quote, full selection set, comparison tie groups, partial coverage and one repair cap. Found that an otherwise valid rate could be accepted under the wrong denominator type; added QuerySpec denominator matching. A comparison result initially lacked that field; fixed and reran tests. Unknown token usage after transport failure remains null rather than false zero.
- Tests: focused verifier/A/B/CLI suite exited 0: 14 passed. Full suite exited 0: 53 passed. Expected wrong rate 0.5 failed, repair to 2/3 passed; persistent wrong rate returned `answer_verification_failed` after exactly two answer calls. Validation is structural and does not establish semantic support for free prose or quotes.

## P3-A — PASS (offline)

- Files: `src/controllers/direct_llm.py`, `tests/test_direct_llm.py`. Self-review checked raw pack completeness, no extraction/query/tool data in request, empty tool trace and failure envelope for invalid schema. Focused suite and full suite above passed. A received all R01–R04 original texts and made one MOCK request. No actual baseline model quality was tested.

## P3-B — PASS (offline)

- Files: `src/controllers/fixed_workflow.py`, `src/controllers/query_parser.py`, `tests/test_fixed_workflow.py`. Self-review checked deterministic recipes, shared parser/finalizer, actual tool traces, metadata refusal, count/rate/selection/comparison and repair failures. Adjusted evidence choice to use negative IDs for negative metrics and combined known parser/finalizer tokens without substituting zero for unknown usage. Focused suite and full suite above passed; rate trace showed numerator 2, denominator 3, one aggregate call; selection called filter then evidence; missing date used only the parser call.

## P3-CLI — PASS (synthetic offline demo)

- Files: `src/demo_mock.py`, `src/cli.py`, `tests/test_cli.py`, `README.md`. The fixture is bound to the exact SHA-256 fingerprint of `data/demo/core.csv` and one exact question. Self-review checked that arbitrary input/question is rejected and `mode=MOCK` is explicit; Method C is not yet exposed as working.
- Actual commands `python -m src.cli extract ... --mock` and `python -m src.cli ask --method a|b ... --mock` each exited 0. Extract returned 4 successes, 0 failures, 4 requests. Both A/B returned rate `0.6666666666666666`; A had no tool trace, B had one `aggregate_aspects` trace with 2/3. Focused CLI test and full 53-test suite passed. CLI's predefined mock response is a plumbing demonstration, not arbitrary natural-language handling or live API validation.
- Phase 3 offline gate: PASS. `git diff --check` had no whitespace error. Next: P4-C. GitHub sync remains NOT AUTHORIZED; local-only work continues.

## Local checkpoint after Phase 3

- Inspected staged Phase 3 paths and made local commit `243dfde79bb3f7d26795ccd85fdb40371c06e3fe` on `main`. No Git remote exists; synchronization status remains NOT AUTHORIZED.

## P4-C — PASS (synthetic offline MVP)

- Files: `src/controllers/dynamic_agent.py`, `src/controllers/__init__.py`, `src/cli.py`, `src/demo_mock.py`, `src/tools/dispatcher.py`, `src/verification/output_checks.py`, `tests/test_dynamic_agent.py`, `tests/test_cli.py`, `tests/test_dispatcher.py`, `docs/data_contract.md`, `README.md`.
- Self-review: checked that all four tools remain available according to real dataset/budget state, no task-type script chooses a mandatory next tool, model history contains actual tool results, invalid/duplicate calls consume budget, no seventh call executes, and parser/finalizer/repair requests are counted separately. Found that failed tool attempts could prevent an otherwise recovered answer, so the verifier now treats only unresolved partial coverage as incomplete; actual numeric support still comes only from successful tools. Tightened query-scope checks to prevent C from grounding a complete answer in an unrelated subset. Evidence text is removed from persisted trace summaries while source IDs remain auditable.
- Functional checks: focused `tests/test_dynamic_agent.py tests/test_output_checks.py tests/test_fixed_workflow.py` exited 0: 16 passed before the final trace update. After the final changes, `.venv/Scripts/python -m pytest -q` exited 0: 61 passed, 0 failed, 0 skipped. Actual `python -m src.cli ask --method c --input data/demo/core.csv --question "What is the negative service rate?" --mock` exited 0; returned `mode=MOCK`, rate 2/3, one aggregate call, two decision rounds and four model requests including parser/final answer. The CLI test also exercised A/B after the final changes.
- Boundaries verified: four unsupported finish decisions returned `insufficient_evidence`; seven proposed parallel calls caused exactly six counted calls and `budget_exceeded`; invalid tool, invalid arguments and duplicate call each consumed one call; invalid decision and timeout consumed rounds. A branching mock examined actual aggregate results: 2 negative service records led to a subsequent evidence call; 0 led to finish. One wrong final numeric claim was repaired once without changing decision/tool counters.
- Phase 4 internal MVP gate: PASS for offline control and plumbing. This does not validate real LLM ABSA, dynamic policy quality or semantic evidence. No tag or remote push. Next: Phase 5 data/evaluation and Phase 6 UI, then Phase 7A offline experiment preparation.

## Local checkpoint after Phase 4

- Inspected staged Phase 4 paths and made local commit `1745b71c62747f964c4bdbada6417b0d3c492bab` on `main`. No Git remote exists; synchronization status remains NOT AUTHORIZED.

## P5-XML and P5-SPLIT — PASS (synthetic code verification)

- Files: `src/semeval.py`, `scripts/prepare_semeval.py`, `tests/test_semeval.py`, `docs/data_sources.md`.
- Self-review: read parser and split code against the official SemEval XML example and source terms. The official task paper says non-commercial, no redistribution through META-SHARE; no mirror data was copied. Parser rejects DTD/entities, malformed category labels and duplicate category gold. Review found a conflicting-label duplicate could still enter dev via first occurrence; changed the rule to exclude all IDs in conflicting duplicate groups from candidate pools and record those IDs. Added source URLs and selected-label distributions to the hashed manifest.
- Functional check: `.venv/Scripts/python -m pytest -q tests/test_semeval.py` exited 0: 5 passed. A synthetic train/test run produced deterministic 2-dev/4-test/2-pack candidate outputs, separate run CSV and gold JSON. Cross-split text and conflicting duplicate labels were audited and excluded. No licensed SemEval files were supplied or processed; actual 150/600 sampling and freeze are pending.

## P5-QUESTIONS — PASS (synthetic code verification)

- Files: `eval/questions.py`, `scripts/build_questions.py`, `tests/test_questions.py`. Self-review checked six task types per pack, no gold fields in runtime question objects, independent reference calculation from gold, undefined rate, tie groups and full source IDs without invented spans. A test initially searched for the string `selected_record_ids` anywhere in the question file, but this correctly appears as an expected field name; corrected the assertion to check that no answer value/key is present in a question object. Focused question+XML suite then exited 0: 8 passed.
- Hand fixture reference matched count 2, rate 2/3, AND selection R1, service ahead of food, and evidence source IDs R1/R2. All outputs remain `CANDIDATE_UNREVIEWED`; no human wording/reference review or frozen formal manifest exists.

## P5-COND and P5-METRICS — PASS (offline code verification)

- Files: `eval/conditioned.py`, `eval/metrics.py`, `tests/test_conditioned.py`, `tests/test_metrics.py`. Self-review separated gold-category-conditioned scoring from joint extraction; the conditioned prompt receives only category names and review text, not gold sentiments. Failed conditioned pairs remain explicit. Metrics use all gold record IDs as denominator, preserve failed extraction, define both-empty selection F1 as 1, track ties/undefined/false refusal and require complete status for primary success. Evidence completion checks source IDs and exact quotes only; human semantic support remains separate.
- Focused conditioned+metric suite exited 0: 7 passed. Full `.venv/Scripts/python -m pytest -q` exited 0: 76 passed, 0 failed, 0 skipped. Expected failed R04 gave category and joint TP=6, FP=0, FN=1, success coverage 3/4. Independent conditioned example gave macro F1 0.6 with a missing gold-category prediction. No real model result is claimed.

## P5-HUMAN / P5-REALDATA — pending external prerequisites

- `docs/annotation_guide.md` contains blank review protocols and headers; no human judgment was fabricated. The original Proposal PDF and licensed SemEval XML files are absent. Official source terms require local access and no redistribution; until authorized files and human review exist, actual dataset manifests, question/reference freeze, challenge labels and formal evaluation remain incomplete. Independent local software work proceeds with synthetic fixtures.

## Local checkpoint after Phase 5 data modules

- Inspected staged paths and made local commit `cac5621586e3592929633e9bf8889f64c18f5eb5` on `main`. No Git remote exists; synchronization status remains NOT AUTHORIZED.

## P5-RUNNER — PASS (synthetic offline dry-run)

- Files: `eval/runner.py`, `eval/run_method.py`, `src/demo_mock.py`, `src/cli.py`, `tests/test_runner.py`, `README.md`.
- Self-review: checked append-only rows, configuration/question/task hashes, resume idempotence, explicit failed attempts, retry cap, unknown usage, pre-request budget checks and no gold in runtime tasks. Found resume would treat an `insufficient_info` answer as a failure and that a cost cap could ignore previous attempts; fixed both. Added row consistency checks and full task payload hash so changed wording cannot reuse an old run. A failed test after changing the task-key encoding was traced to its outdated test fixture condition; corrected it and reran.
- Functional check: `.venv/Scripts/python -m pytest -q tests/test_runner.py` exited 0: 6 passed, 0 failed, 0 skipped. CLI tests also passed. Actual `python -m eval.run_method --method a|b|c --split demo --mock --out outputs/runs/smoke-*` each exited 0 and wrote one MOCK row. Observed service rate 2/3 for each method; physical request totals A=1, B=6 (4 extraction + parser + answer), C=8 (4 extraction + parser + 2 decisions + answer). Repeating C with identical config reported `recorded=0, skipped_existing=1`, preserving the prior row. No live calls or formal data were used.
- Runner `--split dev/test` and gold/ablation/challenge branches currently reject with explicit errors until their prerequisites/implementations exist. The code gate passes for the demo dry-run; Phase 5 as a whole remains incomplete due to licensed real data and human review.

## Local checkpoint after Phase 5 runner

- Inspected staged runner paths and made local commit `0e6832ec6371f79a7337addfee2068a05f91e2ea` on `main`. No Git remote exists; synchronization status remains NOT AUTHORIZED.

## P6-STATE / P6-DATA / P6-ANALYSIS / P6-ASK / P6-COMPARE — PASS (local synthetic UI)

- Files: `app.py`, `.streamlit/config.toml`, `src/ui_state.py`, `src/demo_mock.py`, `pyproject.toml`, `requirements.lock.txt`, `tests/test_app.py`, `tests/test_ui_state.py`, `README.md`.
- Self-review: checked upload size and UTF-8 parsing, source fingerprint, typed extraction alignment, synthetic/provided extraction provenance, query scope, record-level charts, local persistence and clearing, ignored upload state and localhost binding. An AppTest assertion initially used the wrong error-message property; fixed it. A later test assumed an arbitrary upload would hit the B/C extraction error, while the earlier demo-only guard correctly rejected it; corrected that expectation. Review found that a user-provided extraction for the same demo text could be passed into canned answer fixtures; added explicit extraction origin so B/C mock questions require the synthetic extraction artifact.
- Installation: `pip install -e '.[dev,ui]'` exited 0 with Streamlit 1.66.0; exact installed dependencies were recorded in `requirements.lock.txt`. Focused `tests/test_app.py tests/test_ui_state.py` exited 0: 5 passed, 0 failed, 0 skipped; Streamlit emitted 10 third-party `Pandas4Warning` notices from its chart utility, with no functional failure.
- Interaction expectations and actual output: AppTest uploaded `core.csv`, loaded four records, extracted four successes, selected negative service evidence (2 distinct records), asked B and received 2/3 with aggregate trace, compared A/B/C, restored answer/comparison in a fresh AppTest session via URL token, and cleared local state. Another test uploaded a different CSV and a validated extraction JSON, then displayed deterministic evidence while rejecting canned Mock QA. An actual `streamlit run app.py --server.port 8506` started on `127.0.0.1`; GET `/` returned HTTP 200 and `text/html`; server was stopped after smoke check.
- Real browser visual QA and real API behavior were not performed. The UI is a complete **synthetic offline demo path**; arbitrary uploaded CSV needs a separately supplied validated extraction JSON for analysis, and general natural-language QA awaits an approved live provider. No genuine experiment results are displayed.

## P7A-GOLD — PASS (synthetic diagnostic)

- Files: `eval/conditions.py`, `eval/run_method.py`, `eval/runner.py`, `data/demo/core_gold.json`, `src/schemas/models.py`, `tests/test_conditions.py`.
- Review: matched every gold record ID to raw records and bound the source SHA-256 into the run config. Gold contains category/sentiment only, so the diagnostic uses the full original sentence as evidence and explicitly marks `full_sentence_unannotated`; it cannot claim rationale-span quality. A remains ineligible for gold substitution. The runtime question/task object receives no gold answer.
- Tests: focused conditions suite exited 0 with 5 passes; full suite after all 7A changes exited 0 with 98 passes (10 third-party Streamlit warnings). Actual B/C gold CLI commands each recorded one MOCK answer and resumable manifest; B used 2, C used 4 requests with zero extraction requests. No formal gold labels were used.

## P7A-ABLATION — PASS (synthetic diagnostic)

- Files: `src/verification/repair.py`, `src/demo_mock.py`, `eval/run_method.py`, `tests/test_output_checks.py`, `tests/test_conditions.py`.
- Review: `verify_outputs=False` bypasses only `check_answer` and its second answer-repair attempt; typed answer schema, tool allowlist and C decision budgets remain. A wrong 0.5 value passed in the ablation test while malformed numeric type failed after one call. This is a software control check, not evidence of comparative model quality.
- Tests: focused verifier/dynamic suite exited 0 with 13 passes; gold/ablation CLI conditions suite exited 0 with 5 passes. Actual `--method c --condition ablation --mock` wrote one answer with 8 requests. Full suite 98 passes.

## P7A-SUBSETS — PASS (candidate generation only)

- Files: `eval/subsets.py`, `scripts/build_subsets.py`, `tests/test_subsets.py`.
- Review: requires 20 complete packs with all six task types, rejects repeated question IDs, selects before reading model results/gold answers, hashes source question objects and manifest, and keeps `CANDIDATE_UNREVIEWED`. Diagnostic/ablation intentionally share the same 30 IDs for a direct C comparison. This is an automatic candidate selection, not human freeze.
- Test: focused suite exited 0 with 1 pass. A 120-question synthetic fixture produced 20 repeat, 30 diagnostic, 30 ablation and 30 evidence IDs; each tested subset covered all 20 packs. Hash tampering and incomplete packs were rejected. Real candidate file generation awaits licensed SemEval files.

## P7A-CHALLENGE — PASS (synthetic extraction dry-run)

- Files: `eval/challenge.py`, `eval/run_challenge.py`, `data/demo/challenge_candidate.json`, `tests/test_challenge.py`.
- Review: challenge is extraction-only, separate from QA scoring. Exact synthetic pair texts prevent canned responses being applied to other reviews. Source hash/config blocks mixing on resume. Output has `scores: null` and `human_labels: null`; no generated or human challenge labels are claimed. One synthetic candidate does not replace 40 human-written pairs.
- Test: focused suite exited 0 with 1 pass. CLI recorded one MOCK pair with two extraction requests, service negative in source and positive in edit; rerun skipped; altered text and altered manifest failed. Full suite 98 passes.

## P7A-REPORT — PASS (synthetic aggregation)

- Files: `eval/report.py`, `scripts/summarize_runs.py`, `data/demo/core_reference.json`, `tests/test_report.py`.
- Review: scorer imports separate gold reference, validates run manifest/row alignment and same-condition task hash, uses latest retained attempt, keeps absent costs null, pairs question/repeat keys and calculates pairwise primary-success differences. Repeats are summarized separately. An actual first smoke report failed because an older development manifest lacked `tasks_sha256`; this was a correct incompatibility rejection. New clean run directories succeeded without mutating old data.
- Tests: focused suite exited 0 with 1 pass; tampered row and duplicate run were rejected. A new actual MOCK report from main A/B/C, gold B/C and C ablation returned six runs, paired main count 1, paired gold count 1 and main-vs-ablation count 1, all explicitly stamped `MOCK_ONLY_NOT_RESEARCH_RESULT`. These perfect synthetic fixture scores are not research findings.

## P7A-BUDGET — PASS (planning arithmetic)

- Files: `eval/budget.py`, `scripts/estimate_budget.py`, `tests/test_budget.py`, `docs/experiment_plan.md`.
- Review: counts 160 A + 190 B + 220 C = 570 planned answer rows; conservative max 2,270 query + 1,200 main extraction + 160 challenge extraction = 3,630 requests, with no cache credit. Prices, source/date and per-request token bounds are required inputs. Pilot, conditioned sentiment and optional work are explicitly excluded and must be added before approval. No provider price is embedded or claimed current.
- Test: focused suite exited 0 with 1 pass. A clearly fixture-only price input gave 3,630 requests and synthetic USD 7.26; negative price validation failed as expected. This is an estimate example, not a spend quote or authorization.

## P7A-BLIND — PASS (synthetic export and blank templates)

- Files: `eval/blind_review.py`, `scripts/make_blind_review.py`, `tests/test_blind_review.py`, `docs/annotation_guide.md`, `docs/report_template.md`.
- Review: exported review items omit method, with a separate local private mapping; random blind IDs and order are preserved in files, and existing mapping cannot be overwritten. Free prose could still self-identify a method, so the guide requires a manual packet check. No human judgments or report data were generated.
- Test: focused suite exited 0 with 1 pass. Three MOCK A/B/C answers yielded three blinded rows, three private mappings and zero labels; overwrite was rejected. Full suite 98 passes.

## Phase 7A software gate and remaining research work

- All offline branch modules passed synthetic tests. The full suite exited 0 with 98 passes, 0 failures, 0 skips and 10 third-party Streamlit `Pandas4Warning` notices. `git diff --check` exited 0; line-ending notices only. CLI challenge and gold/ablation commands exited 0. Real pilot, licensed SemEval manifests, frozen human-reviewed questions/references, 40 adjudicated pairs, 30-question evidence review, a live provider adapter and formal experiment are still blocked by missing files, human work and separate approval.
- The original Proposal PDF remains absent. No GitHub synchronization was authorized; work remains local.
