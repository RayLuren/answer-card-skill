# v0.5.0 数据契约

## `ai_paper_job.revision-R.attempt-N.json`

Job schema version 为 2，只允许：

- `batch_id`、`paper_id`
- `attempt`：当前 revision 内只能为 1 或 2
- `revision`：0 为首次视觉检查，人工确认后从 1 递增
- 固定 `prompt_path`
- 不可变 `source_pdf`、`source_pages_dir`、`page_count`
- `human_confirmation_path`：revision 0 必须为 null
- 唯一 `allowed_output_path`

Job 不得包含 outline、skeleton、OCR 文本、页面文字、候选题号或上一 attempt 的结构结论。

## `ai_paper_spec.json`

正式 schema version 为 1。顶层只允许 `schema_version`、`status`、`questions` 和 `review_items`。

### `status: ready`

`questions` 必须非空，`review_items` 必须为空。每题包含：

- `number`：AI 归一化的显示题号；脚本不检查重复、连续、顺序或层级合理性。
- `title`：安全简短印刷标题，无法安全确认时用 `第{number}题`。
- `score`：正数大题总分。
- `percent`：1 至 100 的整数。
- `percent_source`：`printed` 或 `derived`。
- `source_page`：1 至 job `page_count`。
- `items`：至少一个答题块。

每个 item 包含 `number`、`source_page`、`kind`、`height`、`fallback_after_reinspection`、`visual_requirement` 和 `visual_type`。

题型和高度范围：

| kind | mm |
| --- | ---: |
| formula | 16–28 |
| short_answer | 20–34 |
| equation | 24–44 |
| calculation | 38–80 |
| drawing | 34–80 |
| mechanism | 55–105 |
| table | 34–80 |
| multi_step | 45–95 |
| long_explanation | 50–100 |
| mixed | 45–95 |

`unknown` 只能使用 `95mm` 且 fallback 必须为 true。其他题型 fallback 必须为 false。

脚本递归拒绝答案、解答、推理、方程/结构正文、摘录、匹配文字、关键词、原因、证据、描述、notes 和 confidence 字段。印刷占比合计不为 100 只记录，不阻断。完整 `ready` 结果不得混用 `printed` 与 `derived`。derived 值由 AI 提供，脚本用精确分数校验它们是否符合按大题分值计算的最大余数分配；余数相同按题目出现顺序处理。脚本只验证，不改写 AI 提交的占比。

### `status: needs_human_review`

`questions` 必须为空。每个 review item 只允许：

- `review_id`：`r001` 形式
- `page`
- `region`：`top`、`upper_middle`、`middle`、`lower_middle`、`bottom`
- `target`：`question_number`、`question_score`、`question_percent`、`item_number`
- `question_index`
- `item_index`：可为 null
- `candidates`：非空字符串列表

不得加入自由原因、摘录或视觉描述。

## `human_confirmation.revision-R.json`

只允许 `schema_version`、`paper_id`、`revision` 和 `decisions`。每项 decision 只有 `review_id` 和非空 `value`。review id 必须与当前请求精确一一覆盖，不允许补充未请求字段。

确认不会直接生成 qspec。它只创建新的视觉 job；新上下文必须读取整卷页面并输出完整 `ready` 结果。

## qspec v2

v2 新增显示题号：

```yaml
schema_version: 2
questions:
  - id: q001
    display_id: "9"
    title: 第9题
    score: 12
    percent: 10
    blocks:
      - id: q001-i001
        display_id: "9-2-1"
        kind: short_answer
        height: 24mm
```

机器键由数组位置生成并必须唯一。渲染只打印 `display_id`，分页、页框对齐、配图绑定和审计关联使用机器键。schema 不检查显示题号重复、父子并存、连续性、数字排序或是否以大题号开头。

旧 qspec v1 仍可读取，其 `id` 同时作为机器键和显示题号。

## `visual_requirements.json`

v2 每题包含 `question_id`、`display_id` 和 `items`；每项包含：

```json
{
  "item_id": "q003-i002",
  "display_id": "9-2-1",
  "visual_requirement": "draw_on_scaffold",
  "visual_type": "coordinate_system",
  "requires_preprinted_visual": true
}
```

绑定 manifest 使用机器 `item_id`，用户报告优先显示 `display_id` 并附机器键。旧 visual manifest v1 仍可读取。

## 报告字段

`pipeline_report.json` 记录 AI status、attempt、revision、人工确认轮次、来源 PDF SHA-256、来源页数、实际总分、printed/derived 占比合计、unknown/95mm 机器题块、配图清单、页数、页框对齐 history 和最终验收结果。它不裁决 AI 题号是否正确。
