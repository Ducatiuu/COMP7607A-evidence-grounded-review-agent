# Development tasks

The user's request authorizes local autonomous development. GitHub publication, paid/live API use, formal holdout evaluation, and human annotation each require separate authorization or human work. The Proposal PDF was not present at project start. No completion claim below covers those items.

| ID | Module and scope | Dependencies | Acceptance | Status | Sync |
|---|---|---|---|---|---|
| P0-SCHEMA | Record, extraction, query, answer and trace types; offline LLM protocol | none | Invalid labels, duplicate IDs, evidence spans and condition forms rejected; offline tests pass | PASS (offline) | NOT AUTHORIZED |
| P0-SETUP | Python package, dependency constraints, repo safety, framework survey, contract docs | none | Clean install/import; docs and tests run | PASS (offline) | NOT AUTHORIZED |
| P1-LOAD | CSV loader and synthetic four-record fixture | P0-SCHEMA | Original text retained; IDs stable and unique; bad rows rejected | PASS (offline) | NOT AUTHORIZED |
| P1-EXTRACT | Prompt, validation, retry and cache | P1-LOAD | Batch ID alignment, exact evidence, bounded retry and cache isolation tests | PASS (offline) | NOT AUTHORIZED |
| P2-FILTER | Typed record filter | P1-EXTRACT | AND/OR exact IDs, failed coverage and bad scope tests | PASS (offline) | NOT AUTHORIZED |
| P2-AGG | Typed aspect aggregation | P1-EXTRACT | Hand counts/rates, null denominator, conflict and partial tests | PASS (offline) | NOT AUTHORIZED |
| P2-COMPARE | Typed aspect comparison | P2-AGG | Ties, undefined values and shared scope tests | PASS (offline) | NOT AUTHORIZED |
| P2-EVIDENCE | Typed source evidence retrieval | P1-EXTRACT | Exact quotes, bad IDs, display limit and failed coverage tests | PASS (offline) | NOT AUTHORIZED |
| P2-PARSER | Shared B/C structured query parser | P0-SCHEMA | Single model parse; invalid and unavailable metadata rejected | PASS (offline) | NOT AUTHORIZED |
| P3-DISPATCH | Allowlisted typed tool dispatcher | P2-FILTER, P2-AGG, P2-COMPARE, P2-EVIDENCE | Valid call, unknown tool and invalid scope handled safely | PASS (offline) | NOT AUTHORIZED |
| P3-VERIFY | Shared B/C answer checks and one repair | P3-DISPATCH | Wrong number, denominator, quote, ID and tie detected; repair bounded | PASS (offline) | NOT AUTHORIZED |
| P3-A | Direct raw-pack Method A | P0-SCHEMA | Complete raw input, no extraction/tools, schema failure retained | PASS (offline) | NOT AUTHORIZED |
| P3-B | Fixed Method B | P1-EXTRACT, P2-PARSER, P3-DISPATCH, P3-VERIFY | Count/rate/selection/comparison/metadata branches and trace tested | PASS (offline) | NOT AUTHORIZED |
| P3-CLI | Offline extract and A/B CLI | P3-A, P3-B | Actual commands yield MOCK output; unsupported fixture rejected | PASS (offline) | NOT AUTHORIZED |
| P4-C | Bounded dynamic C controller | P3-B | Four rounds/six calls boundaries; feedback changes next action | PASS (offline) | NOT AUTHORIZED |
| P5-XML | Local SemEval restaurant XML parser and gold separation | P1-LOAD | Real source hash, category validity, unsafe XML and ID checks | PASS (synthetic tests) | NOT AUTHORIZED |
| P5-SPLIT | Duplicate/overlap audit and deterministic candidate packs | P5-XML | Seeded 150/600/20×30 logic and exclusion audit on fixtures | PASS (synthetic tests) | NOT AUTHORIZED |
| P5-QUESTIONS | Six candidate questions per pack and independent gold reference code | P5-SPLIT | Hand-calculated fixture, null/ties/empty and gold separation | PASS (synthetic tests) | NOT AUTHORIZED |
| P5-COND | Independent gold-category-conditioned sentiment prompt | P5-XML | Prompt omits gold sentiment; failed pairs retained | PASS (offline) | NOT AUTHORIZED |
| P5-METRICS | ABSA and QA evaluation metrics | P5-QUESTIONS | F1, exact, undefined, tie, false refusal and failure tests | PASS (offline) | NOT AUTHORIZED |
| P5-HUMAN | Question/reference/challenge/evidence human review | P5-QUESTIONS | Two independent reviewers and adjudication as specified | PENDING HUMAN WORK | NOT AUTHORIZED |
| P5-REALDATA | Licensed SemEval acquisition and actual candidate manifests | P5-XML, P5-SPLIT | Authorized local files, hashes, distributions, overlap audit | BLOCKED: files/terms absent | NOT AUTHORIZED |
| P5-RUNNER | Resumable offline experiment runner | P3-B, P4-C, P5-METRICS | Failure retention, MOCK dry-run and config-safe resume | PASS (synthetic demo) | NOT AUTHORIZED |
| P6-STATE | Local UI state and refresh restore | P1-LOAD | UUID-scoped ignored storage, validation, clear and refresh tests | PASS (local) | NOT AUTHORIZED |
| P6-DATA | Streamlit CSV and extraction ingress | P6-STATE, P1-EXTRACT | Demo/upload validation, limits and provenance shown | PASS (offline) | NOT AUTHORIZED |
| P6-ANALYSIS | Aspect summary and evidence controls | P6-DATA, P2-FILTER, P2-AGG, P2-EVIDENCE | Tool-backed counts, chart, exact source, partial status | PASS (offline) | NOT AUTHORIZED |
| P6-ASK | Synthetic A/B/C question interaction | P6-DATA, P3-A, P3-B, P4-C | MOCK answer, denominator, trace and restricted arbitrary data | PASS (synthetic demo) | NOT AUTHORIZED |
| P6-COMPARE | A/B/C shared-extraction view and results status | P6-ASK | Same fixture and shared B/C artifact, costs and MOCK labels | PASS (synthetic demo) | NOT AUTHORIZED |
| P7A | Offline experiment branches, budget checks and report scripts | P5-RUNNER, P5-QUESTIONS | All branches dry-run with explicit MOCK outputs | PENDING | NOT AUTHORIZED |

Status reflects verified work, not intention. Each module gets a separate review and test entry in `PROGRESS.md` before PASS.
