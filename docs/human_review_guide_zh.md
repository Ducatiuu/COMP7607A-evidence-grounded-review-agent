# **抽取差异人工审核指南**

## 一、SemEval Gold：

**1. SemEval Gold（数据集参考标签）**：这是 SemEval 数据集提供的原始标注结果，包括评论涉及的方面（Category，如 Food、Service、Price 等）及对应的情感（Sentiment，如 Positive、Negative 等）。它是我们的参考标准，但不代表绝对不会存在标注歧义。

SemEval Gold 是数据集提供的参考标注，由两个字段构成：

```
{
  "category": "food",
  "sentiment": "positive"
}
```

### 1. Category：5 种方面类别

| Category                  | 中文含义       | 具体例子                 |
| ------------------------- | -------------- | ------------------------ |
| `food`                    | 食物           | 味道、菜品、食材、饮料   |
| `service`                 | 服务           | 服务员态度、上菜速度     |
| `price`                   | 价格           | 价格贵不贵、性价比       |
| `ambience`                | 环境氛围       | 装修、噪音、餐厅气氛     |
| `anecdotes/miscellaneous` | 整体体验及其他 | 整体评价、推荐、个人经历 |

例如：

I would happily return to this restaurant.

意思是：我很乐意再次来这家餐厅。

这句话表达的是对餐厅整体的喜爱，并没有明确评价具体的食物质量。

在这个**虚构示例**中，可以标注为：

```
anecdotes/miscellaneous + positive
```

### 2. Sentiment：4 种情感类别

| Sentiment  | 中文 | 说明                     |
| ---------- | ---- | ------------------------ |
| `positive` | 正面 | 表达喜欢、满意、赞扬     |
| `negative` | 负面 | 表达不满、批评           |
| `neutral`  | 中性 | 陈述事实，没有明显褒贬   |
| `conflict` | 冲突 | 对同一个方面存在正反情感 |

例如：

- “The food was delicious.” → `food + positive`
- “The service was terrible.” → `service + negative`
- “The restaurant serves Italian food.” → `food + neutral`（若按任务规范认定为该方面的中性评价）
- “Some dishes were excellent, but others were awful.” → `food + conflict`

需要特别注意：Conflict 指同一个方面有正面和负面情感。 如果 Food 是 Positive，Service 是 Negative，这是两个方面各自不同的情感，不自动属于 Conflict。

## 二、模型预测：有哪些分类？

**2. 模型预测（DeepSeek Prediction）**：这是我们开发的 Agent 使用 DeepSeek 对同一条评论进行分析后得到的结果。除了预测 Category 和 Sentiment，还会提供 Evidence（从原文提取的证据片段）。一条评论可能同时涉及多个方面，因此模型也可能输出多个标签。

DeepSeek 的模型预测使用与 SemEval Gold 完全相同的 5 种 Category 和 4 种 Sentiment。

```
{
  "category": "food",
  "sentiment": "positive",
  "evidence": [
    "The food was delicious"
  ]
}
```

| 字段        | 作用                 | 可填写内容         |
| ----------- | -------------------- | ------------------ |
| `category`  | 判断评论涉及哪个方面 | 上述 5 种          |
| `sentiment` | 判断这个方面的情感   | 上述 4 种          |
| `evidence`  | 从原文提取证据       | 一个或多个原文片段 |

例如：

> The food was amazing, but the service was slow.

模型可以抽取一个或多个方面，下面提供两个方面的例子：

```
[
  {
    "category": "food",
    "sentiment": "positive",
    "evidence": ["The food was amazing"]
  },
  {
    "category": "service",
    "sentiment": "negative",
    "evidence": ["the service was slow"]
  }
]
```

`evidence` 必须是原始评论中实际存在的文字，但引用存在并不代表情感判断一定正确。

## 三、程序发现的差异：有哪些类型？

**3. 程序发现的差异（Detected Differences）**：这是程序自动比较 SemEval Gold 和模型预测后生成的差异提示，包括 `missing_category`（模型漏掉 Gold 中的类别）、`extra_category`（模型预测了 Gold 中没有的类别）和 `wrong_sentiment`（同一类别的情感判断不一致）。**这些差异只表示两者不一致，并不意味着模型一定错误。** 例如，模型把 Gold 中的“整体体验”预测成“食物”，程序可能记录一条 missing 和一条 extra，但本质上可能只是一次类别判断偏差。

程序实际使用以下 3 种 `kind`。

| kind               | 中文含义   | 具体解释                                   |
| ------------------ | ---------- | ------------------------------------------ |
| `missing_category` | 漏掉方面   | Gold 有这个 Category，模型没有预测出来     |
| `extra_category`   | 多预测方面 | 模型预测了某个 Category，但 Gold 没有      |
| `wrong_sentiment`  | 情感不一致 | Gold 和模型都有同一个 Category，但情感不同 |

### 1. missing_category

Gold：

```
service + negative
```

模型：

```
food + positive
```

程序发现 Gold 中的 Service 没有被模型预测，于是生成：

```
{
  "kind": "missing_category",
  "category": "service",
  "gold_sentiment": "negative"
}
```

### 2. extra_category

模型预测了 Food，但是 Gold 没有 Food，因此生成：

```
{
  "kind": "extra_category",
  "category": "food",
  "predicted_sentiment": "positive"
}
```

### 3. wrong_sentiment

Gold：

```
service + negative
```

模型：

```
service + positive
```

两者都识别到了 Service，但情感不一致。

```
{
  "kind": "wrong_sentiment",
  "category": "service",
  "gold_sentiment": "negative",
  "predicted_sentiment": "positive"
}
```

## 四、6 种人工判断类型及其依据

| 判断类型               | 中文含义     | 什么时候选择                                                 |
| ---------------------- | ------------ | ------------------------------------------------------------ |
| `model_error`          | 模型错误     | 原文明确支持 Gold，模型预测不合理                            |
| `annotation_ambiguity` | 标注歧义     | 原文存在不同的合理理解，或者 Gold 标注本身值得进一步裁定     |
| `both_or_mixed`        | 混合问题     | 同一条评论包含多个差异，而且不同差异的原因不一样             |
| `false_discrepancy`    | 程序误报差异 | Gold 和模型实际上没有需要记录的标签差异，是程序比较或数据对齐出了问题 |
| `no_issue`             | 差异可接受   | 差异真实存在，但根据原文和标注规范，Gold 与模型两种读法都可接受，且不需进一步裁决 |
| `unresolved`           | 无法确定     | 根据当前原文和标注规范，审核者无法给出有依据的结论           |

### 1. `model_error`：模型确实预测错了

评论：

> The service was terrible.

Gold：`service + negative`

模型：`service + positive`

原文中的 terrible 明确表达负面评价。Gold 符合原文，模型却预测 Positive。

选择 model_error

判断理由可以写：

> The review clearly expresses negative sentiment about service, but the model predicts positive.

### 2. `annotation_ambiguity`：标签存在合理歧义

评论：

> The restaurant was interesting.

Gold：`anecdotes/miscellaneous + positive`

模型：`anecdotes/miscellaneous + neutral`

单独看 interesting，可能表达赞赏，也可能只是描述餐厅特别。没有更多语境时，情感方向并不十分明确。

选择 annotation_ambiguity

判断理由：

> The word "interesting" could express positive or neutral sentiment depending on context.

这种情况不应该直接判定模型错误。

如果原文明确支持模型预测，而 Gold 似乎标错了，也应在当前审核协议下先使用 `annotation_ambiguity` 记录待裁定的 Gold 问题，并说明理由，而不是偷偷修改 Gold。

### 3. `both_or_mixed`：同一条评论有不同原因的差异

评论：

> The food was awful, but the atmosphere was interesting.

假设 Gold 是：

- `food + negative`
- `ambience + positive`

模型是：

- `food + positive`
- `ambience + neutral`

这里有两个差异：

- Food：awful 明确为负面，模型预测 Positive，这是模型错误。
- Ambience：interesting 的情感可能存在歧义。

一条评论同时出现模型错误和标注歧义。

选择 both_or_mixed

判断理由：

> Food sentiment is clearly misclassified, while ambience sentiment is ambiguous.

注意：多个差异不一定选 `both_or_mixed`。 如果两个差异都是模型错误，仍可选择 `model_error`。只有原因不同才使用混合类型。

### 4. `false_discrepancy`：程序把不存在的差异报了出来

这里先只检查一件事：**程序列出的差异，和同一条评论的 Gold、模型预测是否对得上？**先核对 `record_id`，再对照两边的 Category 和 Sentiment。

例如，某条评论的 Gold 是 `service + negative`，模型预测也是 `service + negative`，程序却报告 `wrong_sentiment`。两边的情感明明相同，这条报告是误报；可能是程序比较错了，也可能是拿错了评论 ID。选 `false_discrepancy`，并在理由中写明哪一项实际相同、哪一项被误报。

> Gold and prediction both label service as negative, but wrong_sentiment was reported. Please check the comparison or record alignment.

**不要用 `false_discrepancy` 表示“我觉得模型是对的”。**看下面两种情况的区别：

| 原文 | Gold | 模型 | 程序报告情感不同，应该怎么选？ |
| --- | --- | --- | --- |
| The service was terrible. | `service + negative` | `service + negative` | `false_discrepancy`：两边相同，程序误报。 |
| The service was terrible. | `service + positive` | `service + negative` | **不能选 `false_discrepancy`**：两边确实不同。原文中的 terrible 支持 negative，Gold 可能有误；按本审核协议选 `annotation_ambiguity`，写清依据，交负责人裁决。 |

简单说：**差异不存在、程序报错 → `false_discrepancy`；差异真实存在、Gold 可能有误 → `annotation_ambiguity`。**审核者只记录判断和理由，不直接改 Gold。

如果之前已下载的审核草稿使用旧值 `no_error`，新版页面在导入时会将其转成 `false_discrepancy`；导出的 CSV 统一使用新值。

### 5. `no_issue`：真实差异可以接受

`no_issue` 表示程序报告的标签差异确实存在，但审核者已核对原文及标注规范，认为两种标法都可接受，且不需要再裁决。选中后 `human_reason` 可留空；程序仍保留这条差异记录。

如果 Gold 可能标错，或两种读法是否都符合规范仍不确定，请选 `annotation_ambiguity` 或 `unresolved`，不要用 `no_issue`。如果程序把本不存在的差异报出来，应选 `false_discrepancy`。

### 6. `unresolved`：暂时无法判断

例如，评论只有：

> Not what I expected.

Gold：`anecdotes/miscellaneous + negative`

模型：`anecdotes/miscellaneous + neutral`

审核者无法根据现有语境及标注规范确定该如何处理，而且不能有把握地选择 `model_error` 或 `annotation_ambiguity`。

选择 unresolved

判断理由：

> Insufficient context to determine the intended sentiment. Further adjudication is needed.

`unresolved` 不是随意跳过问题，而是明确说明还缺少什么判断依据。

# **正式候选题人工审核指南**

## 1. 我们要做什么？

我们的 Agent 项目准备了 **120 道正式测试题目**，用于后续比较 Method A、B、C 的回答效果。

这些题目及其参考答案目前由程序自动生成，**还没有经过人工确认**。

## 2. 120 道题是怎么来的？

项目准备了 600 条餐厅评论：

- 分成 **20 个 Pack**（P01～P20）。
- 每个 Pack 包含 **30 条评论**。
- 每个 Pack 有 **6 道不同类型的题目**。

所以总共是：

**20 × 6 = 120 道题。**

例如：`P01-Q1` 表示第 1 个 Pack 的第 1 道题。

## 3. 我们怎么审核一道题？

以下是**虚构示例题**，不对应正式题库中的任何题号：

**题目：**

> How many reviews express positive sentiment about ambience?

中文：有多少条评论对环境表达了正面情感？

**假设候选参考答案：5 条。**

审核员需要查看当前 Pack 中的 30 条评论及其 SemEval Gold 标签，确认是否真的有 5 条评论被合理标注为 `ambience + positive`。

如果确认正确，就可以通过对应的审核项；如果发现数量或标注有问题，需要记录原因。

**不要因为程序显示答案是 5，就直接认为它一定正确。**

## 4. 每道题需要填写什么？

每道题都需要填写以下 4 个判断：

| 审核字段           | 检查内容                         |
| ------------------ | -------------------------------- |
| `wording_ok`       | 题目表达是否清楚？               |
| `answerability_ok` | 是否能根据提供的数据按预期回答？ |
| `denominator_ok`   | 统计分母的定义是否正确？         |
| `reference_ok`     | 程序生成的参考答案是否正确？     |

**填写规则：**

- `yes`：经过核对，认为该项正确。
- `no`：发现问题，需要说明原因。
- `proposed_edit`：有问题时填写建议如何修改。
- `notes`：记录判断理由或发现的问题。全部判断为 `yes` 时可以留空；有 `no` 时须在本栏或 `proposed_edit` 中说明。

## 5. 六种题目分别检查什么？

| 题目类型                         | 主要审核内容                       |
| -------------------------------- | ---------------------------------- |
| Count（数量）                    | 评论数量是否统计正确               |
| Rate（比例）                     | 分子、分母和比例是否正确           |
| Selection（筛选）                | 筛选出的评论 ID 是否正确、完整     |
| Comparison（比较）               | 各类别数量、排序和并列情况是否正确 |
| Evidence Explanation（证据解释） | 统计结论及对应的证据 ID 是否正确   |
| Insufficient Info（信息不足）    | 题目是否确实缺少回答所需的信息     |

**举例：**

如果题目要求计算服务负面评价比例：

- 30 条评论中，12 条提到了 Service。
- 其中 5 条对 Service 持 Negative 情感。

那么比例应该是 **5 ÷ 12 ≈ 41.67%**，而不是 5 ÷ 30。

审核时需要检查具体的统计范围。

# **HTML 审核操作与提交**

1. 解压各自的审核包，使用 Chrome 或 Edge 打开 `review.html`。选择审核类型后，先导入同包内 `01_extraction/reviewer_N.csv` 或 `02_questions/reviewer_N.csv`；未导入时不能开始审核。
2. 页面自动显示 Reviewer 1 为 R1、Reviewer 2 为 R2，不需要手动填写审核代号或日期。
3. 在“抽取差异（13）”中逐条阅读原文、Gold 和模型预测。`no_issue` 可不填理由直接完成；`false_discrepancy` 表示程序误报，必须解释。其他问题判断也需说明依据。首次完成时自动记录本机日期，后续修改保留该日期。
4. 在“正式候选题（120）”中逐题阅读问题、候选参考答案及对应的 30 条评论，独立填写四项 yes/no。全部为 yes 时修改建议和备注可留空；有 no 时须填写说明或建议。非 Rate 题的分母显示 N/A，导出时按审核协议记为 yes；Rate 题仍需核对分母及零分母。
5. 不确定或发现问题时认真填写备注，不能为了完成任务直接全部选择 yes。“已完成”仅代表必填字段齐全，不代表审核通过。
6. 两部分分别点击“下载当前 CSV”，定期备份并将最终两份 CSV 交给项目负责人。下次继续时导入上次保存的 CSV；页面不会自动恢复此前未导出的编辑。

两名审核员必须分别完成全部 13 条差异和 120 道题，不能互相参考判断。分歧由负责人后续裁决，不修改原始 Gold 或候选参考答案。

“待复核”表示该条审核已完成，但正式题目有 `no`，或抽取差异选择了 `annotation_ambiguity`、`both_or_mixed`、`false_discrepancy`、`unresolved`，需要负责人后续检查。选择 `no_issue` 且完成审核时不显示“待复核”。
