# 当前验证进度

**更新：2026-11-27。** 早期逐模块记录与版本流水账已移至[历史记录](archive/PROGRESS_through_2026-11-27.md)；本页只保留已核实的研究状态和证据入口。

| 阶段 | 当前结论 | 证据位置（本地 `outputs/` 受限，Git 忽略） |
| --- | --- | --- |
| Agent 与开发集 Pilot | A/B/C、DeepSeek、工具、验证和 Streamlit 已实现；v9 开发集 30 评论/10 题已运行 | `dev_pilot_live_deepseek_flash_v9_2026-11-24/`、`dev_pilot_scores/` |
| 正式材料审核与冻结 | P01/P06/P11/P16 的 24 题经两名组员审核，负责人裁决；最终题目、参考答案、数据与规则按哈希冻结 | `formal_freeze_release_2026-11-27/release.json`、`formal_question_review_audit_2026-11-27/` |
| 真实 A/B/C | 4 个共享抽取任务与 72 个回答任务全部完成；280 次请求 | `formal_runs/final_v1_unrun/` |
| 独立 strict 评分 | A 3/24，B 19/24，C 19/24；72/72 评分一致性审计通过 | `formal_scores/final_v1_strict_2026-11-27/`、`formal_score_consistency_audit_2026-11-27/` |
| Evidence 评价 | 12 条匿名回答经负责人报告的三人共同讨论裁定；Claim Support、Completeness 分别为 A 0/4、B 4/4、C 4/4 | `formal_research_analysis_2026-11-27/final_group_consensus_2026-11-27/` |
| 研究分析 | 配对、六题型错误、请求/Token/成本、P01 敏感性分析和 Results/Limitations 草稿已形成 | `formal_research_analysis_2026-11-27/` |

冻结 strict 评分与组内 Evidence 评价是两个不同指标。Evidence Explanation strict 为 A 0/4、B/C 1/4；组内语义 Claim Support 为 A 0/4、B/C 4/4。组内讨论没有两份独立人类评分表，不能报告独立评审一致性系数。P01 冻结前曾用于废弃题目的探索性调用；论文须披露。

**开发集抽取差异：**两名组员各完成 13 条独立审核。负责人已裁决两项类别分歧；原始意见和 Gold 未改动。另有一条虽然两人均选 `both_or_mixed`，但对具体差异的原因解释相反，仍待负责人裁定。逐条记录保存在本地 `extraction_review_v8_2026-11-24/`。

**Challenge 文字定稿：**40 对 Codex 草案已有两份逐对文字审核意见：15 对双方接受，24 对 yes/no 不一致，另有一对双方提出不同修订。负责人已对 25 对争议文字作出决定：23 对保留原句、2 对采用 R1 修订；40 对最终文本与原始意见按哈希绑定，保存在本地 `data/challenge/final_text_2026-11-27/`。这仅完成文字定稿，不是方面/情感 Gold。

**目前尚未完成：**40 对 Challenge 的两份独立方面/情感标注、裁决与真实实验，以及一条开发集抽取差异的原因裁决和最终课程论文提交。未完成工作不得冒充已验证结论。

关键来源哈希由本地 `formal_research_analysis_2026-11-27/final_group_consensus_2026-11-27/FINAL_RESULT_PROVENANCE.json` 绑定；公开仓库仅保留代码、实验协议与脱敏摘要。正式复现步骤见[Runner](formal_runner.md)、[Scorer](formal_scoring.md)，数据边界见[来源说明](data_sources.md)。
