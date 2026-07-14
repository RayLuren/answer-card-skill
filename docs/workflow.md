# 工作流说明

[返回文档导航](README.md)

生产流程由一条确定性主线和两个受控反馈环组成。主 README 保存用户可见的 Mermaid 总览；本文说明每个阶段的职责、输入、输出和停止条件。

## 阶段 0：建立任务级计时

新任务先运行 `scripts/pipeline_timer.py begin`。同一份试卷的后续脚本向同一个 `pipeline_report.json` 追加阶段记录，不覆盖已有运行。Agent 自己执行的视觉检查用 `start` / `stop` 标记，确定性脚本自动追加各自阶段。

## 阶段 1：提取无答案结构

参考 PDF 只用于提取题号、章节、主问题分值和来源页，输出 `build/outline.json`。随后生成 `build/ai_layout.skeleton.json`，锁定 question id、item id、顺序和分值，视觉槽位保持空白。

如果源页面看起来存在 outline 未记录的印刷小题号，必须先修正 outline；不能在 AI layout 中发明 id。

## 阶段 2：联合视觉判断

fresh-context 视觉任务同时判断：

- 答题块 `kind` 和 `height`
- 固定七类 `visual_requirement`
- 固定枚举 `visual_type`
- 标题中印刷的分值和百分比来源

不能为了配图需求另跑第二次 AI 筛选。只有第一次 `kind` 判断为 `unknown` 时，才允许对原始页面证据显式复查一次。如果仍不能确定，必须保留 `unknown`、使用 `95mm` 高度并标记 `fallback_after_reinspection: true`。

## 阶段 3：验证、审计和配图需求导出

每份 `ai_layout.json` 写出后立即通过 `src/answercard/ai_layout_schema.py` 校验，并与 outline 做结构冲突审计。question id、item id、分值或已提取百分比不一致会停止该试卷，而不是静默合并。

校验通过后，确定性导出 `visual_requirements.json`。它只包含 id、固定分类和派生的 `requires_preprinted_visual`，不包含解释、摘录、匹配文字或置信度。

## 阶段 4：生成 qspec

outline 和 AI layout 合并为 `spec/qspec.draft.yaml`，再通过 `src/answercard/schema.py` 严格校验。配图筛选状态不进入 qspec v1。

## 阶段 5：整块分页

`src/answercard/layout.py` 以完整 block 为最小单位规划分页。接近页尾时，阈值百分比规则可以适度缩小当前 block，或在下一 block 会留下极小无用碎片时扩展当前 block；不会跨页拆分一个 block。

## 阶段 6：渲染和首次编译

`src/answercard/render_tex.py` 使用 `tex/front_page.tex.j2` 和 `tex/main.tex.j2` 生成 `build/answercard.tex`，再由 `scripts/build.py` 调用 XeLaTeX。

最终每一页都在底部居中显示阿拉伯页码，包括首页。页码使用 `\QuestionTitleFont`，使数字字体、字号和字重与大题标题中的题号及分数数字一致。

## 阶段 7：页框对齐反馈环

启用对齐时，`src/answercard/frame_alignment.py` 以 `200 DPI` 扫描页面水平框线。初始 PDF 记为 `pass 0`；非末页上、下边缘差异超过默认 `1.1mm` 时调整页面间距并重新编译，默认最多进行三次修正。

无论成功还是失败，`build/frame_alignment.json` 和流水线报告都保留无答案的逐 pass 测量历史。

## 阶段 8：页面预览和基本检查

`scripts/render_pages.py` 将最终 PDF 渲染为 `page-001.png` 起始的逐页 PNG。预览数量必须与 PDF 页数严格一致。

## 阶段 9：最终验证门

`scripts/finalize_pipeline.py` 校验 qspec、配图需求覆盖、页数、A4 几何、敏感短语、编译日志、页框对齐和预览文件，并将结果写入 `build/pipeline_report.json`。

显式传入的 `.tmp` 证据路径无论成功或失败都清理。成功构建默认保留审计产物；只有显式打包副本才使用 `--prune-on-success`。

## 阶段 10：任务报告

所有试卷都成为 `validated` 或 `failed` 后，运行 `scripts/write_task_report.py` 一次。报告开头的 `一分钟总览` 必须列出：

- 仍需图片的试卷和 item id
- 不确定的视觉案例
- 未正确导出的试卷和近似失败原因
- 页框对齐失败时的最终超标量

后续明细保留阶段耗时、冲突、非 100% 印刷总和、`unknown` 95mm fallback、参数偏差和逐 pass 对齐记录。

## 配图后处理

自动流程交付无图初稿。若报告列出预印图形需求，等待人工提供获准的题面侧素材；随后只修改生成的 TeX，直接重编译并检查修改页及相邻页。不得重新读取答案内容或从答案图形恢复题面素材。

## 阶段与文件对应表

| 阶段 | 主要实现 | 主要产物 |
| --- | --- | --- |
| 结构提取 | `extract_outline.py` | `outline.json` |
| skeleton | `ai_layout_skeleton.py` | `ai_layout.skeleton.json` |
| 视觉 job | `batch.py`、固定 prompt | `ai_layout.attempt-N.json` |
| AI layout 接纳 | `ai_layout_schema.py`、`ai_layout_audit.py` | `ai_layout.json` |
| 配图需求 | `visual_requirements.py` | `visual_requirements.json` |
| qspec | `ai_layout_to_qspec.py`、`schema.py` | `qspec.draft.yaml` |
| 分页 | `layout.py` | 内存中的页面计划 |
| 渲染与编译 | `render_tex.py`、`build.py` | `answercard.tex`、`answercard.pdf` |
| 页框对齐 | `frame_alignment.py` | `frame_alignment.json` |
| 预览 | `render_pages.py` | `pages/page-*.png` |
| 最终验证 | `finalize_pipeline.py` | `pipeline_report.json` |
| 任务报告 | `task_report.py` | `task-report.md` |
