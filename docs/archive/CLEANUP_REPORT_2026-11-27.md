# Repository cleanup record · 2026-11-27

The project entered report preparation after its four-Pack A/B/C run, strict Gold score, paired analysis, and final group Evidence discussion. This cleanup changed documentation and removed redundant **local generated packets**. It did not change Agent code, tests, prompts, Gold, final questions, reviewer originals, frozen manifests, live traces, or formal scores.

## Main documentation

- **Rewritten:** root `README.md`, `docs/PROJECT_PROGRESS_ZH.md`, `docs/PROGRESS.md`, `docs/TASKS.md`, `docs/experiment_plan.md`, and `docs/proposal_alignment.md`. They now describe the completed run and distinguish strict scoring, final group Evidence evaluation, and unfinished Challenge work.
- **Archived before rewriting:** the previous full `PROGRESS.md`, `TASKS.md`, `experiment_plan.md`, and `proposal_alignment.md`. Their source hashes and current archive hashes are in `cleanup_archive_manifest_2026-11-27.json`. Two archive-relative links were adjusted so the snapshots remain navigable.
- **Archived and removed from the main docs folder:** `DOCUMENTATION_CLEANUP_PLAN.md`, the empty `report_template.md`, and the early `framework_survey.md`. Their contents remain in this archive and Git history.
- **Marked historical without changing the procedure:** Pack selection, Stage 4 freeze, formal Runner and Scorer instructions. The data-source page now states that the licensed XML was actually obtained and used.

## Local generated outputs

Deleted 16 directories containing only superseded blank reviewer packets or a byte-identical unzip copy of the final Evidence packet. They comprised the early `human_review_packets_2026-11-24`, versions `v2`–`v12`, two older 13+24 handoffs, one extraction-only handoff, and the extracted `evidence_review_packet/` folder. All old reviewer CSVs inside those ZIPs were checked for empty human judgments; the final Evidence ZIP and filled review records were retained. The deletion list, file hashes, and sizes are saved locally in ignored `outputs/cleanup_manifest_2026-11-27.json`. Approximately 3.39 MB of duplicate generated material was removed.

**Retained:** the completed R1/R2 formal question sheets and owner adjudication, frozen release and final references, all official run and score journals, formal audit reports, pre-freeze P01 exploration needed for disclosure, development Pilot evidence, and final group Evidence decisions. `data/raw/`, `data/gold/`, and `outputs/` remain Git ignored.

## Verification

- 63 local Markdown links checked, 0 broken.
- Seven archived snapshots checked against their recorded current SHA-256 hashes.
- Five key formal research artifacts confirmed present.
- Full `.venv/Scripts/python.exe -m pytest -q`: **284 passed**, 20 dependency warnings.
- `git diff --check`: no whitespace errors (Git only reported expected line-ending notices).

The pre-existing untracked root file `任务进度.md` was not modified. No GitHub push or paid model call was made during cleanup.
