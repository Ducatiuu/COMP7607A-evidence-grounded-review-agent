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
| Results 与 Limitations 更新草稿 | 已纳入 Challenge 与开发集差异裁决，待整合进完整论文 |
| 40 对 Challenge 的双人标注、负责人裁决、真实抽取及离线评分 | 已完成；与 A/B/C 问答成绩分开报告 |

## 核心结果

正式 strict 正确率：A **3/24（12.5%）**，B **19/24（79.2%）**，C **19/24（79.2%）**。B/C 逐题对错完全相同，但 19/24 题的回答内容或结构化字段不同。Evidence Explanation 的 strict 得分为 A **0/4**、B **1/4**、C **1/4**。

项目负责人报告本人和两位组员共同讨论了 12 条匿名 Evidence 回答，最终五维评价为：Source Fidelity **12/12**、Relevance **12/12**、Sentiment Support **12/12**、Claim Support **8/12**、Completeness **8/12**。其中 Claim Support 与 Completeness 按方法分别为 A **0/4**、B **4/4**、C **4/4**。这项评价检验语义证据质量，不能和 24 题 strict 正确率混为一个分数；原始代理审核及负责人的 11 项待定裁定均有本地记录。没有两位组员分别提交的独立审核 CSV。

正式日志共 **280 次 API 请求、332,244 输入 Token、39,370 输出 Token**；按冻结单价估算费用 **USD 0.1469172**。B/C 共享的 120 次 ABSA 抽取只计一次。样本每题型仅四题，不做总体精度或因果增益断言。P01 在冻结前曾用于一次废弃题目的探索性调用，论文需披露；排除 P01 的补充分析为 A **2/18**、B/C **15/18**，不替代主结果。

独立 Challenge 使用 **40 对、80 条**经人工定稿和双人标注的对照句子，真实 DeepSeek 抽取完成 80/80；**81 次请求、25,832 输入 Token、4,818 输出 Token**，估算费用 **USD 0.0135312**。冻结 Gold 评分：目标变化 **34/40（85%）**，不变方面 **39/39（100%）**，整对通过 **34/40（85%）**。CH018 没有不变方面类别，故稳定方面分母为 39。否定/转折/隐含方面/同方面冲突各 10 对，整对通过分别为 10/10、8/10、7/10、9/10。六对未通过均是修改后句子的目标情感与 Gold 不符。这些句子源自 Codex 草案并经人工审核，不是人工原创数据；结果不并入 A/B/C 的 24 题成绩。

## 余下工作

1. 将本地已更新的 `outputs/formal_research_analysis_2026-11-27/final_group_consensus_2026-11-27/RESULTS_AND_LIMITATIONS_DRAFT.md` 整合入完整课程报告，补齐摘要、引言、方法、外部文献引用及最终格式。
2. 13 条开发集抽取差异已有两份完整独立审核；10 条意见一致，另 3 条经负责人最终裁决。Challenge 的原始材料、人工 Gold、真实输出和独立评分已本地存档；论文需要分开说明其来源、指标与样本规模。
3. 最终提交前检查课程要求与受限数据边界，不上传 `data/raw/`、Gold、审核表或 `outputs/`。

主要公开文档：[README](../README.md)、[实验计划](experiment_plan.md)、[Proposal 对照](proposal_alignment.md)、[数据来源](data_sources.md)、[人工审核规范](annotation_guide.md)。真实结果与最终讨论记录保存在 Git 忽略的 `outputs/formal_research_analysis_2026-11-27/`、`outputs/formal_scores/` 和 `outputs/formal_runs/`，不会随 GitHub 仓库分发。
