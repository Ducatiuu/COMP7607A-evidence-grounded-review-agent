# Framework survey — 2026-11-22

Read-only checks used each repository's GitHub API metadata, default-branch commit and root listing; no third-party code was copied or executed. The listed SHA is the observed default branch HEAD on this date, not a pinned upstream dependency. Repository metadata reporting no license is treated as **unverified permission to reuse**, so implementation is original.

| Repository | Observed SHA | Relevant observed paths | License seen in metadata | Decision |
|---|---|---|---|---|
| [Sentari](https://github.com/nishnarudkar/Sentari) | `aad0687945383f8fc2d75be23101b79b4d2d76aa` | `absa_service/`, `agents/`, `dashboard/`, `evaluation/` | none reported | Design reference for separated extraction and audit; financial domain and multi-agent structure do not fit the small restaurant project. No reuse. |
| [DanceHA](https://github.com/Tom-Owl/DanceHA) | `6a4cd111a23171a68afe8869081cf6dd394ad675` | `code/`, `data/`, paper PDF | none reported | Document-level agent research reference only. No reuse. |
| [ai-absa](https://github.com/chtr302/ai-absa) | `b8884af32c2f3acc262d986dd27303f0efeda50d` | `src/`, `templates/`, `static/`, `pyproject.toml` | none reported | Interface and evaluation organization reference only. No reuse. |
| [Codex](https://github.com/openai/codex) | `1476a08f1b410e359e64becf2494bc248743e396` | root `LICENSE`, `CHANGELOG.md` | Apache-2.0 reported | General bounded tool-control design reference; no code reuse or dependency. |
| [awesome-verified-agents](https://github.com/tonydzi/awesome-verified-agents) | `8ce5109de74a08277845e0367ed22b4b3939d771` | `README.md`, `LICENSE` | MIT reported | Checklist inspiration for inspectable artifacts. No code reuse. |

Deeper file and implementation review is deferred until a concrete reuse decision is needed. The Proposal was absent at survey time and has since been reviewed; see `docs/proposal_alignment.md` for the requirement audit.
