# 人工审核包：Reviewer __SLOT__（R__SLOT__）

本包包含 **13 条开发集抽取差异**和 **24 道正式候选题**。正式题来自固定选择的 P01、P06、P11、P16；每个 Pack 有 30 条评论、6 道题。选择规则为按 P01–P20 编号每隔 5 个取一个，从 P01 开始；选择发生在正式 A/B/C 模型运行之前，与模型表现无关。原始 120 题另行保留；这 24 题目前仍是**待审核候选题**，尚未冻结。

## 开始和保存

1. 解压本包，用 Chrome 或 Edge 打开 `review.html`。先阅读本说明，再选择审核类型。
2. 抽取差异导入 `01_extraction/reviewer___SLOT__.csv`；正式候选题导入 `02_questions/reviewer___SLOT__.csv`。未导入对应 CSV 时不能开始该部分审核。
3. **每次离开前，在两部分分别点击“下载当前 CSV”。**下次继续时分别导入自己上次下载的 CSV；网页不会自动恢复未下载的修改。

页面固定审核者为 R__SLOT__；抽取差异首次完成时记录本机日期。请独立判断，不参考另一位审核者的结论，也不要查看正式 A/B/C 预测。

## 一、抽取差异：13 条

对照**同一 `record_id`**的原文、SemEval Gold、模型预测及程序报告。下列例子为虚构案例，不代表本包真实结论。

| 选项 | 含义与例子 |
| --- | --- |
| `model_error` | 原文支持 Gold，模型预测错误。例如 “The service was terrible.”，Gold 为 `service: negative`，模型却判为 positive。 |
| `annotation_ambiguity` | 原文或 Gold 的解释有合理争议，需要裁决。例如 “The restaurant was interesting.” 的 positive 与 neutral 难以确定。 |
| `both_or_mixed` | 同一评论有多个差异，**且原因不同**。只有多个同类差异不选此项。 |
| `false_discrepancy` | 程序误报差异。例如 Gold 和模型都是 `service: negative`，程序却报告 `wrong_sentiment`。 |
| `no_issue` | 核对后，模型判断、Gold 和程序报告都无须纠正或裁决。例如程序正确报告不同标签，而标注规范明确允许两种标法；若是否允许仍有争议，则选 `annotation_ambiguity`。 |
| `unresolved` | 目前依据不足，暂时无法判断。 |

先核对程序是否误报；误报选 `false_discrepancy`。报告属实后再判断模型、Gold 或整条记录。`no_issue` 的理由可留空；其他选项须写理由，尽量引用原文。不要修改 Gold。旧版 CSV 中的 `no_error` 导入时会转为 `false_discrepancy`。

## 二、正式候选题：24 题

每题对照所属 Pack 的 30 条评论、Gold 标签及**待审核**参考答案，独立填写以下四项。

| CSV 字段 | 中文解释 | 审核重点 |
| --- | --- | --- |
| `wording_ok` | 表述清晰 | 问题是否明确，有无歧义。 |
| `answerability_ok` | 可按预期回答 | 根据该 Pack 的数据，能否给出题目要求的回答。设计为“信息不足”的题，若确实缺少所需信息，可以选 `yes`。 |
| `denominator_ok` | 分母定义正确 | Rate 题的分母和零分母处理是否正确。非 Rate 题页面显示 N/A，导出 CSV 按协议写 `yes`，只表示不适用。 |
| `reference_ok` | 候选答案正确 | 独立核对答案的数值、类别、评论 ID 和证据是否符合 Gold 与题意。 |

每项选 `yes` 或 `no`。例如 10 条评论提到 Service，其中 4 条为负面，相关比例是 4/10；若分母为 0，比例是未定义（`null`），不能写成 0。四项都为 `yes` 时，修改建议和备注可留空；**只要有一项为 `no`，就须写说明或修改建议**。页面显示答案不代表它已被确认。

## 交回

分别交回页面下载的 `reviewer___SLOT___extraction_filled.csv` 与 `reviewer___SLOT___questions_filled.csv`。“已完成”只表示必填字段完整；“待复核”表示负责人还需检查。负责人汇总两人的独立判断并裁决分歧后，才能确认是否冻结这 24 题。

不要修改评论、ID、Gold、候选参考答案、题目或哈希字段。`readonly/` 包含所选 120 条评论及对应 Gold、24 题及参考答案、标注规范；`MANIFEST.json` 记录来源和文件哈希。材料仅供获准组员使用，**不要上传到公开 GitHub**。
