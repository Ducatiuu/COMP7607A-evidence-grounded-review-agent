# COMP7607A Agent · 当前进度

**最后更新：2026-11-27 · 阶段：论文收尾**

本项目实现了餐厅评论的方面情感分析、原文 Evidence、确定性分析工具与结果验证，并在同一批正式题目上比较直接回答（A）、固定工作流（B）和动态 Agent（C）。

## 已验证的进展

| 工作 | 状态 |
| --- | --- |
| Agent、DeepSeek 接口、Streamlit 演示与开发集 Pilot | 已完成 |
| 选定 24 道正式题的人工审核、裁决与本地冻结 | 已完成 |
| P01/P06/P11/P16 共 120 条评论、72 个 A/B/C 回答 | 已完成，原始 trace 保留本地 |
| 冻结 strict Gold 评分及逐题一致性审计 | 已完成，72/72 判定一致 |
| 配对、错误、请求/Token/成本分析 | 已完成 |
| 12 条 Evidence 回答的组内讨论最终评价 | 已完成；与 strict 评分分开报告 |
| Results 与 Limitations 初稿 | 已完成，待整合进最终论文 |

## 核心结果

正式 strict 正确率：A **3/24（12.5%）**，B **19/24（79.2%）**，C **19/24（79.2%）**。B/C 逐题对错完全相同，但 19/24 题的回答内容或结构化字段不同。Evidence Explanation 的 strict 得分为 A **0/4**、B **1/4**、C **1/4**。

项目负责人报告本人和两位组员共同讨论了 12 条匿名 Evidence 回答，最终五维评价为：Source Fidelity **12/12**、Relevance **12/12**、Sentiment Support **12/12**、Claim Support **8/12**、Completeness **8/12**。其中 Claim Support 与 Completeness 按方法分别为 A **0/4**、B **4/4**、C **4/4**。这项评价检验语义证据质量，不能和 24 题 strict 正确率混为一个分数；原始代理审核及负责人的 11 项待定裁定均有本地记录。没有两位组员分别提交的独立审核 CSV。

正式日志共 **280 次 API 请求、332,244 输入 Token、39,370 输出 Token**；按冻结单价估算费用 **USD 0.1469172**。B/C 共享的 120 次 ABSA 抽取只计一次。样本每题型仅四题，不做总体精度或因果增益断言。P01 在冻结前曾用于一次废弃题目的探索性调用，论文需披露；排除 P01 的补充分析为 A **2/18**、B/C **15/18**，不替代主结果。

## 余下工作

1. 将本地 `outputs/formal_research_analysis_2026-11-27/final_group_consensus_2026-11-27/RESULTS_AND_LIMITATIONS_DRAFT.md` 的事实和图表整合入最终课程报告，核对引用与格式。
2. 13 条开发集抽取差异已有两份完整独立审核；两项类别分歧已由负责人裁决，一条混合原因仍待裁定。40 对 Challenge 已按两份文字审核和负责人决定定稿；方面/情感独立标注、裁决和真实实验尚未开展。未完成部分不得写成正式结果。
3. 最终提交前检查课程要求与受限数据边界，不上传 `data/raw/`、Gold、审核表或 `outputs/`。

主要公开文档：[README](../README.md)、[实验计划](experiment_plan.md)、[Proposal 对照](proposal_alignment.md)、[数据来源](data_sources.md)、[人工审核规范](annotation_guide.md)。真实结果与最终讨论记录保存在 Git 忽略的 `outputs/formal_research_analysis_2026-11-27/`、`outputs/formal_scores/` 和 `outputs/formal_runs/`，不会随 GitHub 仓库分发。
