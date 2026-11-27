# Research report data template

Status: **EMPTY TEMPLATE — no real model or human results entered**.

## Provenance and approvals

| Item | Reviewed value / evidence |
|---|---|
| Dataset license, source and SHA-256 | |
| Dev/test and question/reference manifest SHA-256 | |
| Human reviewers and freeze record | |
| Challenge adjudication record | |
| Provider/model/version, parameters and prompt version | |
| Scorer version and pilot/formal approval | |

## ABSA and QA

| Condition | Method | Paired questions | Complete / failed / missing | Primary success | Category/joint F1 | Notes |
|---|---|---:|---:|---:|---:|---|
| Main | A | | | | N/A | |
| Main | B | | | | | |
| Main | C | | | | | |
| Gold diagnostic | B/C | | | | | |
| C verification ablation | C | | | | | |
| Repeats | A/B/C | | | | | |

Report per-task count, rate, selection F1/exact, comparison ties, evidence completion, insufficient-info detection, false refusal and equal-type average. State null denominators, partial coverage and failures separately. Human evidence support and claim coverage require blinded labels; structural citation validity is distinct. Challenge change/stability accuracy requires independently adjudicated labels. Do not copy MOCK values into these tables.

## Efficiency and limitations

| Stage/condition | API requests | Input/output tokens | Cost basis and total | Median/P95 latency | Failures/cache |
|---|---:|---:|---:|---:|---|
| Shared extraction | | | | | |
| A queries | | | | | |
| B queries | | | | | |
| C queries | | | | | |
| Challenge extraction | | | | | |

Record cold-start and repeated-query cost with shared physical extraction separated from logical method attribution. Describe real failures, human disagreement, uncertainty at pack level and changes from the planned protocol.
