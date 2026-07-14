# 数据契约

[返回文档导航](README.md)

本项目通过严格的 JSON/YAML 中间层将参考 PDF 检查、AI 判断和确定性渲染分开。所有契约只允许答案无关的结构元数据；未知字段默认拒绝，而不是忽略。

## `outline.json`

结构提取器只允许写入：

- `source`
- `questions[].id`
- `questions[].title`
- `questions[].score`
- `questions[].page`
- `questions[].items[].id`
- `questions[].items[].page`

`questions[].score` 是大题分值。小题分值、答案正文、题型、答题块类型和高度都不属于 outline。

提取器必须过滤科学计数法等上下文中的伪小题号，例如 `× 10-4` 和 `10-12.67`。

## `ai_layout.skeleton.json`

skeleton 由 outline 确定性生成，只锁定 question id、item id、顺序和分值。它不能预填或暗示 `kind`、`height`、百分比和视觉分类。

视觉 Agent 只能填充空的决策槽位，不能改变 skeleton 结构。

## `ai_layout.json`

每个 question 必须显式包含：

- `id`
- 从题目标题视觉读取的 `score`
- `percent`
- `percent_source`
- 非空的 items

`percent_source` 必须是契约允许的来源。标题中存在可见百分比时使用 `printed` 并原样保留，即使总和不是 100。标题确实没有百分比时，才根据所有大题分值使用确定性的最大余数法分配并标记为 `derived`；报告必须列出派生项，不能将其描述为印刷值。

每个 item 使用固定字段，包括：

- `id`
- `kind`
- 带单位的正 `height`
- `fallback_after_reinspection`
- `visual_requirement`
- `visual_type`

允许的布局 kind：

- `short`
- `medium`
- `long`
- `derivation`
- `table`
- `drawing`
- `mixed`
- `unknown`，仅限一次显式复查后仍无法判断

不同 kind 的高度必须落在固定 prompt 规定的正值范围内。`unknown` 只能与 `95mm` 和 `fallback_after_reinspection: true` 组合；qspec 转换时渲染为 `mixed` 95mm，但报告必须保留并突出原 fallback。

固定视觉需求分类：

- `modify_existing_visual`
- `complete_existing_visual`
- `draw_on_scaffold`
- `draw_from_scratch`
- `visual_reference_only`
- `no_visual`
- `uncertain`

只有前三类派生为需要预印题面图形。`uncertain` 的派生结果为 `null`，等待后续复核。

`visual_type` 使用固定枚举，覆盖化学结构、示意图、坐标系、表格、网格、反应框架、流程图、仪器装置、其他、无和不确定。

禁止加入自由文本证据、`review_notes`、匹配文字、关键词、摘录、理由、数值置信度、方程、答案或化学结构。

### id 覆盖规则

AI layout 必须精确覆盖 outline 中所有 item id。没有印刷小题号且只有一个完整答题区的大题，可以使用大题 id 本身作为唯一 block id，例如 `2`，不能虚构 `2-1`。

视觉证据显示存在遗漏的印刷小题号时，应停止并修正 outline，不能在 AI layout 中创建 `question-*` 或其他合成 id。

## `visual_requirements.json`

该文件由经验证的 AI layout 确定性导出，包含：

- question/item id
- 固定 `visual_requirement`
- 固定 `visual_type`
- 派生 `requires_preprinted_visual`

它是答案无关的结构 manifest，不保存原因、图形描述、OCR 文本、置信度或答案内容。其 item 覆盖必须与最终 qspec block 完全一致。

配图状态保持在 qspec v1 之外。

## qspec v1

顶层字段：

- `schema_version: 1`
- `paper`
- `style`
- 非空 `questions`

主要对象为 `PaperSpec`、`StyleSpec`、`QuestionSpec`、`BlockSpec` 和 `AnswerCardSpec`。`load_spec(path)` 读取 YAML 后必须先调用 `validate_spec(data)`。

`paper` 包含正式标题、是否省略首页和总分。标题必须由流水线显式输入，不能从参考答案文件名或 `outline.source` 推断。`paper.total_score` 必须等于所有大题分值之和。

每个 question 需要唯一正整数形式的 `id`、`title`、正 `score`、整数 `percent` 和非空 blocks。

block 只允许：

- `id`
- AI 批准的 `kind`
- 带 `mm` 或 `pt` 的正 `height`
- 可选 `force_page_break_before`

自由文本 `raw_heading`、`note`，拼错的 `hight`，缺少高度，未知 kind，重复或归属错误的 id，以及未知字段都必须失败。

## 报告契约

`pipeline_report.json` 只能记录路径、状态、阶段耗时、页数、预览数量、测量值、固定警告、结构冲突、百分比总和、fallback id 和配图 item id。

其 `result.alignment_history` 每项只包含：

- `pass`
- `top_spread_mm`
- `bottom_spread_mm`
- `tolerance_mm`
- `passed`

成功和失败都必须保留该无答案历史。完整报告行为见[验收与报告](validation-and-reporting.md)。
