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
| P3-AB | Direct A, fixed B, shared generator and verifier | P1-EXTRACT, P2-TOOLS, P2-PARSER | Offline tests and actual CLI smoke tests | PENDING | NOT AUTHORIZED |
| P4-C | Bounded dynamic C controller and dispatcher | P3-AB | Four rounds/six calls boundaries; feedback changes next action | PENDING | NOT AUTHORIZED |
| P5-DATA | SemEval parser, audited splits, manifests and annotation templates | P1-LOAD | Source/hash/overlap checks; missing human review shown as pending | PENDING | NOT AUTHORIZED |
| P5-EVAL | Metrics and resumable offline experiment runner | P3-AB, P4-C | Failure retention, independent references and MOCK dry-run | PENDING | NOT AUTHORIZED |
| P6-UI | Streamlit upload, analysis and comparison | P3-AB, P4-C | Interactive offline demo path and clear MOCK status | PENDING | NOT AUTHORIZED |
| P7A | Offline experiment branches, budget checks and report scripts | P5-DATA, P5-EVAL | All branches dry-run with explicit MOCK outputs | PENDING | NOT AUTHORIZED |

Status reflects verified work, not intention. Each module gets a separate review and test entry in `PROGRESS.md` before PASS.
