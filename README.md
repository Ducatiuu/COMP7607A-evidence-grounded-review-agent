# COMP7607A — Evidence-Grounded ABSA Agent

**最后更新：2026-11-27 · 当前阶段：论文收尾**

[查看中文项目进度](docs/PROJECT_PROGRESS_ZH.md)

本项目使用 DeepSeek 分析英文餐厅评论：抽取方面、情感和原文证据，再回答计数、比例、筛选、比较与信息不足问题。研究比较同一批评论和题目上的三种方法：

| 方法 | 工作方式 |
| --- | --- |
| A | 直接把原始评论和问题交给 LLM |
| B | 共享 ABSA 抽取后，按固定工作流调用确定性工具 |
| C | 使用与 B 相同的抽取，动态选择工具、验证结果并有限修正 |

## 已完成的正式研究

正式材料在运行前固定为 **P01、P06、P11、P16**：每 Pack 30 条评论和六类题，共 120 条评论、24 题。题目与参考答案经人工审核和裁决后冻结；真实 A/B/C 运行、独立 strict Gold 评分及一致性审计已完成。每种方法的分母均为 24：

| 严格评分 | A | B | C |
| --- | ---: | ---: | ---: |
| 总体正确 | **3/24 (12.5%)** | **19/24 (79.2%)** | **19/24 (79.2%)** |
| Evidence Explanation | 0/4 | 1/4 | 1/4 |

对 12 条 Evidence Explanation 回答的最终组内讨论评价，Claim Support 和 Completeness 均为 A **0/4**、B **4/4**、C **4/4**。这是语义证据质量评价；上表是冻结结构化 Gold 评分，两项口径和分母分别保留。完整分析、成本与局限见[当前进度](docs/PROJECT_PROGRESS_ZH.md)及本地受限结果。正式 24 题的 72 个方法回答全部有记录；B/C 共用 Pack 级抽取。

独立的 40 对 Challenge 抽取实验也已完成：目标方面变化 **34/40**，不变方面 **39/39**，整对通过 **34/40**。文本由 Codex 起草、组员审核并由负责人定稿；两名组员独立标注后形成了人工裁决 Gold。该结果单独报告，不并入上表的 A/B/C 问答成绩。

## 功能与快速启动

- 读取英文餐厅评论 CSV，抽取 Food、Service、Price、Ambience 等方面、情感和原文引用。
- 使用确定性工具统计数量、比例、评论 ID 和类别比较；记录验证、模型请求、Token、耗时与失败状态。
- Streamlit 页面支持 CSV 上传、抽取及 A/B/C 问答；无密钥时可使用合成 MOCK 演示。

在项目根目录使用 Python 3.12：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev,ui]"
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m streamlit run app.py
```

真实模型调用需要使用者在本机配置自己的 DeepSeek API Key。课程数据、Gold、审核表、密钥和真实运行输出均不应上传公开 GitHub。

## 文件夹与文档

| 位置 | 内容 |
| --- | --- |
| [app.py](app.py)、[src/](src/) | Web 入口与 Agent 核心实现 |
| [eval/](eval/)、[scripts/](scripts/) | 指标、正式执行、评分及辅助命令 |
| [tests/](tests/) | 自动化测试 |
| [configs/](configs/) | 可公开的候选配置；正式冻结版本在本地 `outputs/` |
| [data/demo/](data/demo/) | 合成演示数据 |
| `data/raw/`、`data/processed/`、`data/gold/`、`outputs/` | 本地受限数据与研究证据；Git 忽略 |

阅读顺序：[中文进度](docs/PROJECT_PROGRESS_ZH.md) → [实验方案与评分口径](docs/experiment_plan.md) → [数据来源](docs/data_sources.md) / [数据契约](docs/data_contract.md) → [人工标注规范](docs/annotation_guide.md)。正式 A/B/C 复现步骤见[Runner](docs/formal_runner.md)和[Scorer](docs/formal_scoring.md)，独立 Challenge 流程见[Challenge Runner](docs/challenge_runner.md)；[当前任务](docs/TASKS.md)与[验证记录](docs/PROGRESS.md)保留简要状态，历史开发流水账在 `docs/archive/`。
