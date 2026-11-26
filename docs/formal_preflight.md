# Four-Pack formal experiment: Plan/Preflight only

This page records the original Stage 1 candidate gate. A later local final version is described in [formal_freeze_stage4.md](formal_freeze_stage4.md); the original candidate lock and plan remain unchanged.

Stage 1 validates the fixed P01/P06/P11/P16 candidate set. It does not execute Method A/B/C, contact DeepSeek, need an API key, score formal results, or freeze human review. `scripts/plan_formal_experiment.py` is separate from the development Pilot and MOCK runner.

## Locked inputs and checks

`configs/formal_24_candidate.lock.json` fixes the four Pack IDs, 24 original question IDs, selected question/reference canonical digests, full source file hashes, prompt versions and scoring rule (`strict`, bound to the current `eval/metrics.py` hash). The two `02_questions/reviewer_N.csv` sheets in the R1/R2 packets contain the same 24 unique questions for independent review. Their rows are checked against original candidate wording, task type, record IDs, reference JSON and subset hashes. A packet ZIP is also checked against its manifest and all file hashes. Direct completed CSVs can be supplied later.

The preflight checks the 20-Pack split, 600 formal and 150 development IDs, exact CSV/split alignment, no dev/test ID overlap, 30 unique records and six distinct task types per selected Pack, 24 unique question IDs, and 120 selected records. The official test Gold is bound by file hash for provenance; its labels are not read by the model. An existing output run directory is rejected.

The planning bound is 240 shared extraction requests plus A 24, B 72 and C 168 requests, **504 total**. The budget gate requires explicit per-request input/output token caps, price assumptions, a positive spend cap at least as large as the worst-case estimate, a timeout and a unique planned run directory. The current local candidate plan uses historical development-Pilot price assumptions only to exercise this offline gate; prices must be verified again before any later live run.

The local candidate preflight is saved under ignored `outputs/formal_plans/`. It reports `CANDIDATE_PREFLIGHT_ONLY`, `PENDING_HUMAN_REVIEW`, `execution_permitted=false`, `network_calls_made=0`, and `formal_runner_implemented=false`. It cannot be used to start a live experiment.

## Release gate for the next stage

After both reviewers return their filled question CSVs, the same preflight can check them. A future `HUMAN_ADJUDICATED` record must identify an adjudicator distinct from R1/R2 and resolve every question with a rejection or disagreement. A separate human-signed `FROZEN` manifest must bind the exact source hashes, both filled review-sheet hashes, adjudication file hash, selected Pack/question IDs and scoring rule. The code validates this structure and hash alignment; it cannot establish whether reviewers actually made sound independent semantic judgments. Those judgments and sign-off remain human responsibilities.

Stage 2 now has a separate runner; see [formal_runner.md](formal_runner.md). `require_formal_execution_ready` remains the original Stage 1 closed sentinel. The Stage 2 `checked_plan` rebuilds this preflight from current files and requires reviewed, adjudicated, frozen materials plus an identical saved plan before any model client can be constructed. A manually changed enable flag is rejected. The candidate plan remains blocked. Offline scoring is reserved for Stage 3.
