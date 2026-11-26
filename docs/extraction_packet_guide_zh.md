# 人工审核包：Reviewer __SLOT__（R__SLOT__）

本包只包含 **13 条开发集 ABSA 抽取差异**。请独立判断，不参考另一位审核者的结果。本包没有正式测试题目；不需要审核 120 道题。

## 开始与保存

1. 解压后，用 Chrome 或 Edge 打开 `review.html`，导入 `01_extraction/reviewer___SLOT__.csv`。未导入 CSV 时不能开始审核。
2. 逐条对照同一 `record_id` 的评论原文、SemEval Gold、模型预测和程序报告的差异。
3. 每次结束前点击 **“下载当前 CSV”**。下次继续时导入上次下载的 CSV；页面不会自动恢复未下载的修改。

页面固定审核者为 R__SLOT__，首次完成一条判断时自动记录本机日期。

## 六种判断

以下例子仅用于说明选项，不是数据中的真实审核结论。

| 选项 | 何时选择；虚构例子 |
| --- | --- |
| `model_error` | 原文支持 Gold，模型预测错误。例如 “The service was terrible.”，Gold 是 `service: negative`，模型却预测 positive。 |
| `annotation_ambiguity` | 原文或 Gold 的解释有合理争议，需要裁决。例如 “The restaurant was interesting.” 的 positive 与 neutral 难以确定。 |
| `both_or_mixed` | 同一评论有多个差异，且原因不同。例如 Food 明显预测错，同时 Ambience 的情感有歧义。仅有多个同类错误不选此项。 |
| `false_discrepancy` | 程序误报：Gold 和模型都是 `service: negative`，程序却报告 `wrong_sentiment`。 |
| `no_issue` | 核对后，模型判断、Gold 和程序报告都无须纠正或裁决。例如程序正确报告了两种不同标签，而标注规范明确允许两种标法。是否允许仍有争议时不选此项。 |
| `unresolved` | 依据不足，暂时无法判断。例如仅有 “Not what I expected.”，缺少判断方面或情感所需的语境。 |

**先检查程序是否误报。**误报选 `false_discrepancy`；程序报告属实后，再判断模型、Gold 或整条记录是否有问题。Gold 可能有误时，写明原文依据，交负责人裁决，不直接修改 Gold。

`no_issue` 的理由可留空；其他选项须填写 `human_reason`。旧版草稿里的 `no_error` 导入时会转成 `false_discrepancy`。

## 交回结果

“已完成”表示必填字段齐全；“待复核”表示负责人还需检查。请交回下载的 `reviewer___SLOT___extraction_filled.csv`，不要修改原文、ID、Gold、预测或差异列。`readonly/annotation_guide.md` 可供查阅标注规则。

本包含受限 SemEval 文本，仅交给获准使用该数据的组员，不要上传公开 GitHub。两人的判断须分别保存；分歧由负责人另行裁决。
