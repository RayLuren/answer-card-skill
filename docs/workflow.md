# 工作流说明

[返回文档导航](README.md)

生产流程由一条确定性主线和两个受控反馈环组成。主 README 保存用户可见的 Mermaid 总览；本文说明每个阶段的职责、输入、输出和停止条件。

## 阶段 0：建立任务级计时

新任务先运行 `scripts/pipeline_timer.py begin`。同一份试卷的后续脚本向同一个 `pipeline_report.json` 追加阶段记录，不覆盖已有运行。Agent 自己执行的视觉检查用 `start` / `stop` 标记，确定性脚本自动追加各自阶段。

## 阶段 1：提取无答案结构

参考 PDF 只用于提取题号、章节、主问题分值和来源页，输出 `build/outline.json`。没有文字层的页面会以 `220 DPI` 在内存中渲染并调用 RapidOCR；OCR 文字和 OCR 页面图像均不写盘，只把通过结构解析的允许字段写入 outline。大题简述以题号附近的原始标题为准：简述在分值前或分值后均可，只有视觉上存在独立简述时才原样保留；若题号附近只有题号、分值并直接进入题干，则使用 `第N题` 占位，渲染时不显示任何简述。不得从题干或答案概括、改写或补造简述。随后生成 `build/ai_layout.skeleton.json`，锁定 question id、item id、顺序和分值，视觉槽位保持空白。

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

`src/answercard/layout.py` 以完整 block 为最小单位规划分页。它先按 LaTeX 模板计算页面实际占用：每个答题块使用 qspec 框高并加上 `style.border_width` 对应的横线厚度；同页出现新大题时计入题号标题的实际行高，标题过长时按可用版心宽度计入额外行高。完成这些固定开销计算后才执行 30% 阈值规则。接近页尾时，该规则可以适度缩小当前 block，或在下一 block 会留下极小无用碎片时扩展当前 block；不会跨页拆分一个 block。

## 阶段 6：渲染和首次编译

`src/answercard/render_tex.py` 使用 `tex/front_page.tex.j2` 和 `tex/main.tex.j2` 生成 `build/answercard.tex`，再由 `scripts/build.py` 调用 XeLaTeX。

最终每一页都在底部居中显示阿拉伯页码，包括首页。页码使用 `\QuestionTitleFont`，使数字字体、字号和字重与大题标题中的题号及分数数字一致。

## 阶段 7：页框对齐反馈环

启用对齐时，`src/answercard/frame_alignment.py` 以 `200 DPI` 扫描页面水平框线。初始 PDF 记为 `pass 0`；非末页上、下边缘差异超过默认 `1.1mm` 时，将高度修正落实到该页的具体答题块，再按题号和框线开销重新执行整块分页与 30% 规则后编译。若分页成员发生变化，旧的页序号顶部补偿立即作废，新页面重新测量；默认最多进行三次修正。

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

## 阶段 11：clean 图片准备与整卷审批

自动流程先交付无图初稿。若报告列出预印图形需求，使用 `scripts/prepare_clean_image.py` 只在外部素材目录生成同目录 `<原名>-clean.png`；它只允许透明铺白、整图亮度转换和单一全局阈值二值化，并使用固定 PNG 编码稳定输出哈希。禁止裁切、缩放、旋转、局部擦除、修补、重绘、内容补全或语义修改。准备阶段不得修改 qspec、TeX、PDF 或报告，不得重新读取答案内容，也不得从完成的答案图形恢复题面素材。

同卷所需 clean 图片确认后，建立严格 `prompt_image_binding.json`。v2 区分 `cleaned` 与 `approved_original`，固定批准源与最终 PNG 的 SHA-256，并可表达默认、横排、右上、底部居中、按框高比例缩放、取消配图、连续块合并和独立框高覆盖；不保存审批人、对话或自由文本。原始 qspec、AI layout 与视觉需求不改写，另存绑定审计副本。缺少必需 item、题号越界、文件缺失或哈希变化均停止执行并要求重新审批。

## 阶段 12：隔离绑定、重新分页与原子发布

`scripts/bind_prompt_images.py bind` 一次处理同卷全部获批图片。默认放置保留原框高；特殊横排可固定重复数和零或非零间距。所有模式均宽高双限制、保持纵横比、相对 A4 页面居中并在四边至少保留 `0.6 mm`。

框高覆盖不修改原 qspec，而是写 `qspec.binding.yaml` 审计副本，然后仅从既有无答案结构重新执行分页、渲染、编译、默认 `1.1 mm` 页框对齐、预览和最终验收。成功后才原子替换正式 PDF，记录审批、嵌入、特殊排列和框高审计并清理临时目录；失败时正式 PDF 不变，诊断保留。单卷可立即重写任务报告；批量任务逐卷绑定后仍只聚合一次任务报告。

## 阶段与文件对应表

| 阶段 | 主要实现 | 主要产物 |
| --- | --- | --- |
| 结构提取 | `extract_outline.py` | `outline.json` |
| skeleton | `ai_layout_skeleton.py` | `ai_layout.skeleton.json` |
| 视觉 job | `batch.py`、固定 prompt | `ai_layout.attempt-N.json` |
| AI layout 接纳 | `ai_layout_schema.py`、`ai_layout_audit.py` | `ai_layout.json` |
| 配图需求 | `visual_requirements.py` | `visual_requirements.json` |
| clean 图片准备 | `clean_image.py` / `prepare_clean_image.py` | 外部素材目录中的 `*-clean.png` |
| 配图审批 | `prompt_image_binding.py` | `prompt_image_binding.json` |
| 配图执行 | `bind_prompt_images.py`、`render_tex.py` | `qspec.binding.yaml`、绑定资产、正式 PDF |
| qspec | `ai_layout_to_qspec.py`、`schema.py` | `qspec.draft.yaml` |
| 分页 | `layout.py` | 内存中的页面计划 |
| 渲染与编译 | `render_tex.py`、`build.py` | `answercard.tex`、`answercard.pdf` |
| 页框对齐 | `frame_alignment.py` | `frame_alignment.json` |
| 预览 | `render_pages.py` | `pages/page-*.png` |
| 最终验证 | `finalize_pipeline.py` | `pipeline_report.json` |
| 任务报告 | `task_report.py` | `task-report.md` |
