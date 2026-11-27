# 当前验证进度

**更新：2026-11-27。当前课程范围的实验阶段已完成，进入论文与讲解视频准备。** 早期逐模块记录与版本流水账已移至[历史记录](archive/PROGRESS_through_2026-11-27.md)；本页只保留已核实的研究状态和证据入口。

| 阶段 | 当前结论 | 证据位置（本地 `outputs/` 受限，Git 忽略） |
| --- | --- | --- |
| Agent 与开发集 Pilot | A/B/C、DeepSeek、工具、验证和 Streamlit 已实现；v9 开发集 30 评论/10 题已运行 | `dev_pilot_live_deepseek_flash_v9_2026-11-24/`、`dev_pilot_scores/` |
| 正式材料审核与冻结 | P01/P06/P11/P16 的 24 题经两名组员审核，负责人裁决；最终题目、参考答案、数据与规则按哈希冻结 | `formal_freeze_release_2026-11-27/release.json`、`formal_question_review_audit_2026-11-27/` |
| 真实 A/B/C | 4 个共享抽取任务与 72 个回答任务全部完成；280 次请求 | `formal_runs/final_v1_unrun/` |
| 独立 strict 评分 | A 3/24，B 19/24，C 19/24；72/72 评分一致性审计通过 | `formal_scores/final_v1_strict_2026-11-27/`、`formal_score_consistency_audit_2026-11-27/` |
| Evidence 评价 | 12 条匿名回答经负责人报告的三人共同讨论裁定；Claim Support、Completeness 分别为 A 0/4、B 4/4、C 4/4 | `formal_research_analysis_2026-11-27/final_group_consensus_2026-11-27/` |
| 研究分析 | 配对、六题型错误、请求/Token/成本、P01 敏感性分析和 Results/Limitations 草稿已形成 | `formal_research_analysis_2026-11-27/` |

冻结 strict 评分与组内 Evidence 评价是两个不同指标。Evidence Explanation strict 为 A 0/4、B/C 1/4；组内语义 Claim Support 为 A 0/4、B/C 4/4。组内讨论没有两份独立人类评分表，不能报告独立评审一致性系数。P01 冻结前曾用于废弃题目的探索性调用；论文须披露。

**开发集抽取差异：**两名组员各完成 13 条独立审核；10 条意见一致，3 条由负责人最终裁决（685、1470、3332）。3332 保留 `both_or_mixed`：漏掉 `service: neutral` 归为模型错误，`ambience` 的 negative/neutral 差异归为合理标注歧义。原始审核意见、SemEval Gold、模型预测及修改前的部分裁决记录均保留；最终比较表与哈希清单位于本地 `outputs/extraction_review_v8_2026-11-24/`。13 条均有处理结论。

**Challenge 文字定稿：**40 对 Codex 草案已有两份逐对文字审核意见：15 对双方接受，24 对 yes/no 不一致，另有一对双方提出不同修订。负责人已对 25 对争议文字作出决定：23 对保留原句、2 对采用 R1 修订；40 对最终文本与原始意见按哈希绑定，保存在本地 `data/challenge/final_text_2026-11-27/`。文本来源仍为 AI 草案、人工审核与定稿，并非人工原创。

**Challenge 标注与冻结：**两份独立组员意见各覆盖 40 对，A/B 方面与情感主标签逐对一致。负责人裁定 CH018 的稳定方面类别为空；CH023 保留两人一致的 Food/Service 主标签，并记录 `satisfied` 的额外解释歧义。原始意见存于本地 `outputs/challenge_label_review_2026-11-27/`；裁决和 40 对 Gold 已按 SHA-256 绑定于本地 `data/gold/challenge_40_2026-11-27/release.json`。逐对核对了 80 个记录 ID、两份标签、变化/稳定类别和来源哈希。

**真实 Challenge 与评分：**独立的 40 对/80 句 DeepSeek 抽取已完成，81 次请求中 CH018-A 有一次结构验证失败并成功重试；80/80 条抽取和 40/40 对预测均留有原始日志。请求/Token/费用、证据原文和输入隔离审计通过。冻结 Gold 离线评分：变化类别及情感 34/40、稳定类别及情感 39/39、整对通过 34/40；各子组支持数均为 10。六对未通过：CH014、CH020、CH025、CH027、CH029、CH039，均在 B 句的目标情感。运行、评分和逐对诊断位于本地 `outputs/challenge_runs/challenge_40_v1_2026-11-27/`、`outputs/challenge_scores/challenge_40_v1_2026-11-27/`。该实验独立于 24 题 A/B/C 主结果；文本是 AI 草案经人工审核，并非人工原创。

**论文草稿更新：**本地 `RESULTS_AND_LIMITATIONS_DRAFT.md` 已纳入 Challenge 结果、13 条开发集差异的最终处理及 3332 的混合原因，并核对 24 题主结果、Evidence 的 12 条分母、P01 的 18 题敏感性分析和 Challenge 的 40/39 分母。负责人最新说明为“两名组员先独立思考、负责人第三人裁定”；Evidence 没有留存两份独立逐项表，因此草稿将该流程归于负责人确认，不报告可计算的评审一致性。旧草稿及更新来源哈希保存在本地；完整论文的引言、方法、外部文献引用与最终排版仍待完成。

**目前尚未完成：**将研究结果与限制整合进最终课程论文，完成讲解视频与课程提交。原提案的重复/消融/Gold 诊断及更大规模独立 Evidence 盲审未执行，须作为范围限制或未来工作，不能冒充已验证结论。

关键来源哈希由本地 `formal_research_analysis_2026-11-27/final_group_consensus_2026-11-27/FINAL_RESULT_PROVENANCE.json` 绑定；公开仓库仅保留代码、实验协议与脱敏摘要。正式复现步骤见[Runner](formal_runner.md)、[Scorer](formal_scoring.md)，数据边界见[来源说明](data_sources.md)。
