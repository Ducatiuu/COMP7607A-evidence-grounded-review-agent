# 文档整理要求与实施方案（待执行）

**盘点日期：2026-11-24。状态：根目录进度首页已按后续要求定向修改，旧 README 快照已归档；其余文档清理仍待执行。**

**后续范围调整：** 用户明确要求 GitHub 根目录直接展示中文进度全文。根目录 `README.md` 因此先采用中文进度作为首页正文，并补充快速启动与目录说明；原先的“仅添加中文进度链接”方案被这一最新要求取代。完整的历史归档和其余文档清理仍待执行。已在 GitHub 网页上传的 [中文进度](../PROJECT_PROGRESS_ZH.md) 保留，仅校正过时测试数字。

## 本次要求

1. 审查项目自有 Markdown，找出重复内容、过期状态和不必要的版本流水账。
2. 将 `README.md` 精简为项目简介、核心功能、Method A/B/C 架构、快速启动和文档导航。
3. 维护中文 `docs/PROJECT_PROGRESS_ZH.md`，简述已验证进度、当前阶段和后续工作；在 README 开头设置中文入口，注明最后更新日期。
4. 精简 `docs/PROGRESS.md` 与 `docs/TASKS.md`，完整历史移入归档，主文档只保留当前状态和待办。
5. 核实 `docs/experiment_plan.md` 与 `docs/proposal_alignment.md`，依据当前代码及真实实验记录修订；旧版内容需要时归档。
6. 保留数据来源、数据协议、人工审核规范，以及正式实验复现需要的配置和来源哈希。
7. 不改 Agent 核心代码、数据、测试或正式实验结果。
8. 不删除支撑研究结论的证据、实验配置或版本来源信息；MOCK、开发集 Pilot 与正式实验继续明确区分。
9. 移动文档后检查相对路径、锚点及 GitHub 上实际可用的内部链接。
10. 提交前列出删除、归档、合并、重写清单与原因，运行 Markdown 链接检查和代码测试；用户自行决定何时上传 GitHub。

README 中文入口拟按用户给出的文字放在标题后：

```markdown
## 📌 中文项目进度

欢迎小组成员查看项目当前的开发情况：

👉 [查看中文项目进度](../PROJECT_PROGRESS_ZH.md)

**最后更新：2026-11-24**
```

## 盘点结果

- 初次盘点时公开仓库跟踪 **12 份**项目 Markdown，本地另有未跟踪的 `docs/PROJECT_PROGRESS_ZH.md` 草稿；用户随后通过 GitHub 网页上传该草稿，现已作为第 13 份被跟踪的文档纳入本地分支。根目录的 `AGENTS-v2.5.md`、`CODEX-v2.5.md` 和本地 checkpoint 被 Git 忽略，属于内部执行文档；`.pytest_cache` 中的 README 是生成物，不列入公开文档整理。
- 初次盘点的 `README.md` 约 17 KB，混合当前简介、历史 v1–v8 调试过程、运行协议和本地成本门禁，阅读入口过重；现已根据后续要求改为中文进度首页。`docs/PROGRESS.md` 约 163 KB、684 行，`docs/TASKS.md` 约 34 KB、128 行，包含需要留存但不适合作为组员首页的逐模块记录。
- `docs/experiment_plan.md` 开头仍写“真实数据 Pilot 尚未运行”，并称真实传输尚未接入 CLI；实际已有 DeepSeek 开发集 v8/v9 Pilot、真实 CSV CLI 和 Streamlit 路径。正式实验 runner 仍为 MOCK 路径，正式 holdout 未运行。
- `docs/proposal_alignment.md` 仍写 30 条/10 题 Pilot “Not run”，以及真实 Provider/演示尚未验证；应按 v9 运行、UI 验证和待完成的正式实验分别修订。
- 已存在的中文草稿正确标明正式材料未冻结，但“最新提交记录为 240 passed”已过期：本次基线为 **244 passed、20 个第三方警告**。草稿需要校准、压缩并纳入 Git；不能直接覆盖掉已有文字。
- `docs/demo_script.md` 的合成 MOCK 演示步骤仍可用，但末尾“真实 Pilot 尚待运行”和结果页措辞需要更新。`docs/data_sources.md` 的来源与许可记录重要，个别“仍需取得数据”的历史句子应标为当时状态或移入归档。
- 初次对项目 Markdown 的显式相对链接检查得到 **11 条本地链接、0 条失效**；README 定向修改后须重新检查。移动其他文档后仍需检查目标与标题锚点。旧 README 对被 Git 忽略的内部计划文档的纯文本提及，已由公开可访问的导航替代。

## 拟议文件处置

| 文件 | 处置 | 原因与保留方式 |
| --- | --- | --- |
| `README.md` | **已定向重写；后续校准** | 按最新要求直接展示中文进度全文，并补充快速启动和目录说明。旧版完整快照存于 `docs/archive/README_pre_homepage_2026-11-24.md`，记录原始 SHA-256；保留候选参考未审、正式实验未运行等边界。 |
| `docs/PROJECT_PROGRESS_ZH.md` | **保留并校订** | 用户已在 GitHub 网页上传此页；本地与远端内容一致。修正过期测试数，之后决定将其作为 README 的简短入口或同步摘要，避免长期维护两份不同的进度全文。 |
| `docs/PROGRESS.md` | **原文归档后重写** | 原文完整保存为 `docs/archive/PROGRESS_through_2026-11-24.md`，主文件只呈现最近验证、当前阻塞、证据索引与下一阶段。 |
| `docs/TASKS.md` | **原文归档后重写** | 原文完整保存为 `docs/archive/TASKS_through_2026-11-24.md`，主文件只列人工审查、正式冻结、真实 A/B/C、Challenge、Evidence、报告等未完成工作和依赖。 |
| `docs/experiment_plan.md` | **旧版归档后重写** | 原文保存为 `docs/archive/experiment_plan_preformal_2026-11-24.md`；新主文件保留数据划分、共享抽取、公平对照、条件、指标、请求/成本/trace 规则、冻结门禁及可复现配置，纠正 Pilot/CLI 状态。 |
| `docs/proposal_alignment.md` | **旧版归档后更新** | 原文保存为 `docs/archive/proposal_alignment_2026-11-24.md`；保留原 Proposal 哈希、研究承诺对照与尚未达成项，更新真实 Pilot 和 UI 状态。 |
| `docs/framework_survey.md` | **归档** | 是有用的早期设计与许可核查证据，不需要在主导航占位；保留原文件内容和来源 commit。 |
| `docs/demo_script.md` | **小幅修订** | 保留明确标注的合成演示，去除与已完成开发 Pilot/真实 UI 冲突的旧状态。 |
| `docs/data_sources.md` | **保留并校准时间表述** | 官方来源、许可、文件身份、哈希/数据边界必须可追溯；不把受限 XML、Gold 或审核包纳入公开文档。 |
| `docs/data_contract.md` | **保留，核对契约版本后再决定小修** | 核心数据结构与计数单位需要明确；旧 Phase 0 名称不能冒充当前版本。 |
| `docs/annotation_guide.md`、`docs/extraction_review_handoff.md` | **保留** | 两人独立审核、裁决和 Evidence/Challenge 标注规范尚在使用。 |
| `docs/report_template.md` | **保留** | 正式报告仍为空模板，不能提前填写开发集或 MOCK 数字。 |
| `AGENTS-v2.5.md`、`CODEX-v2.5.md`、`.codex-local/CHECKPOINT.md` | **仅内部检查，不纳入公开主导航** | 当前被 Git 忽略；实施时如主文档路径调整，只更新必要的内部引用，不公开原 Proposal 或本地恢复信息。 |

**拟删除：无。** 旧 README 已归档，其他拟议归档尚未执行。“归档”采用保留原文与内容哈希的移动/副本方式；确认新主文档、相对链接和 Git 差异后才完成迁移。重复的运行流水账留在归档，不作为首页入口。

## 复现与验收约束

- 开发集 v9 是 Train 来源 30 条、10 题、A/B/C 各 10 题的真实 DeepSeek Pilot；30 条抽取结构有效，98 次实际请求。候选参考答案和语义证据仍未人工确认，不能当正式研究结果。正式 150/600、20×30、120 候选题仍未冻结。保留来源哈希、prompt/scorer 版本和 one-shot trace 的索引；公开文档只给脱敏摘要，真实运行产物继续留在 ignored 本地目录。
- 新 `experiment_plan.md` 必须说明 Method A 仅看原文，B/C 共享同一抽取与验证；比例按 distinct record 定义分子/分母；MOCK runner 与真实开发集 runner 的边界；正式 holdout、Challenge 和 Evidence 的人工门禁。不得在整理中改变评分口径或研究约束。
- 实施后先比较归档文件与原文的 SHA-256，检查 Git 暂存列表不含 `data/raw/`、`data/gold/`、`outputs/`、审核包、密钥或原 Proposal；再扫描所有 Markdown 相对链接及锚点，并从仓库根目录运行 `.venv/Scripts/python -m pytest -q`。本轮仅做了清理前基线：**244 passed、20 warnings；11 条本地链接均可定位**。
- 用户先要求审阅清理方案，随后明确要求根目录直接展示进度，因此已单独更新 README 首页并归档旧 README。其他文件的归档迁移和批量清理仍未执行；GitHub 推送留给用户。
