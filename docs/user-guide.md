# 使用指南

[返回文档导航](README.md)

项目提供两种主要使用方式：面向开发和调试的单份工程流程，以及由 Codex 托管的可恢复目录批处理流程。生产批量任务优先使用后者。

## 安全前提

参考答案只能短暂用于读取题目结构和估计答题空间。任何生成的 JSON、YAML、LaTeX、PDF、日志、测试或文档都不得包含答案正文、最终答案、解析、摘录方程或答案图形。

视觉页面证据必须位于项目 `.tmp/` 或批处理 job 指定的临时目录，并在终态后清理。不要生成 contact sheet，不要从完成的答案图形中裁剪或重建题面素材。

## Codex 托管批处理

### 最简用户入口

向 Codex 提供输入目录和输出根目录：

```text
调用 <本地 answer-card-skill 项目目录>，
处理 <输入目录> 下的答案 PDF，
输出到 <输出根目录>。
```

Codex 必须先读取 [`references/codex-batch-orchestration.md`](../references/codex-batch-orchestration.md)，再调度 fresh-context 整卷视觉 worker。Python 核心不依赖 Codex thread API。

### 稳定命令

```powershell
.\.venv\Scripts\python scripts\batch_pipeline.py prepare INPUT OUTPUT_ROOT [--metadata INPUT\answercard-batch.yaml] [--visual-workers N]
.\.venv\Scripts\python scripts\batch_pipeline.py status RUN\batch_manifest.json
.\.venv\Scripts\python scripts\batch_pipeline.py accept-ai-layout RUN\batch_manifest.json PAPER_ID RUN\.work\PAPER_ID\ai_layout.attempt-N.json
.\.venv\Scripts\python scripts\batch_pipeline.py build RUN\batch_manifest.json [--paper PAPER_ID]
.\.venv\Scripts\python scripts\batch_pipeline.py fail-paper RUN\batch_manifest.json PAPER_ID --code CODE
.\.venv\Scripts\python scripts\batch_pipeline.py report RUN\batch_manifest.json
```

`prepare` 只扫描输入目录第一层的 PDF，按稳定顺序分配 `paper001`、`paper002` 等内部 id，并创建新的非覆盖目录：

```text
run-YYYYMMDD-HHMMSS-input/
├── 成功卷答题卡.pdf
├── task-report.md
├── run-report.json
├── batch_manifest.json
├── batch_state.json
├── audit/paper001/
├── failed/paper002/
└── .work/
```

成功 PDF 只在最终验证后发布到运行目录根部；无答案审计产物进入 `audit/`，失败工作区和安全诊断进入 `failed/`。终态试卷的源页面证据必须清理。

### 标题和输出文件名

默认标题会从文件名末尾移除 `参考答案`、`答案` 或 `详解` 及相邻分隔符，再添加 `答题卡`。可在输入目录放置 `answercard-batch.yaml`：

```yaml
schema_version: 1
papers:
  任意文件名.pdf:
    title: 定制答题卡标题
    output_name: 定制输出.pdf
```

未知文件、未知字段、无效映射和重复的显式输出名会被拒绝。自动生成的重名会追加 `-paperNNN`。manifest 保存文件名、字节数和 SHA-256，恢复时不会静默接受被替换的源文件。

### 状态和重试

正常状态流为：

```text
prepared → awaiting_ai_layout → ai_layout_running → ai_layout_valid → building → validated
```

`failed` 是终态。第一次可恢复的 AI attempt 失败会回到 `awaiting_ai_layout` 并创建 attempt 2；第二次失败后整卷终止。结构冲突、源指纹变化、能力预检失败和安全拒绝不重试。worker 槽位不足只是排队，不是试卷失败。

每个 item 的 `unknown` 第二次视觉复查发生在同一个 worker attempt 内，不消耗整卷重试次数。

`report` 只能在所有试卷到达 `validated` 或 `failed` 后调用，并且整个任务只调用一次；重复调用返回已有报告。

## 单份工程流程

以下步骤适合开发、调试或手工运行。AI 判断本身不能由确定性脚本代替。

### 1. 启动计时并提取结构

```powershell
.\.venv\Scripts\python scripts\pipeline_timer.py begin --label "paper-name"
.\.venv\Scripts\python scripts\extract_outline.py fixtures\reference_answer.pdf build\outline.json
.\.venv\Scripts\python scripts\prepare_ai_layout_skeleton.py build\outline.json build\ai_layout.skeleton.json
```

### 2. 完成视觉判断

```powershell
.\.venv\Scripts\python scripts\pipeline_timer.py start ai_layout_judgment
```

视觉 Agent 使用固定 prompt、outline、skeleton 和原始逐页视觉证据写出 `build/ai_layout.json`。验证通过后立即停止阶段计时：

```powershell
.\.venv\Scripts\python scripts\pipeline_timer.py stop ai_layout_judgment
```

### 3. 运行确定性流水线

```powershell
.\.venv\Scripts\python scripts\full_pipeline.py `
  fixtures\reference_answer.pdf `
  --paper-title "正式试卷标题答题卡"
```

`full_pipeline.py` 是已有 `build/ai_layout.json` 之后的规范入口。它默认包含首页并启用答题区页框对齐。只有明确需要正文时才使用 `--omit-front-page`。

直接调用 `scripts/build.py` 默认只编译一次；只有传入 `--align-pages` 才启用对齐循环。

### 4. 最终验收

```powershell
.\.venv\Scripts\python scripts\finalize_pipeline.py `
  --front-pages 1 `
  --temp-path .tmp\source-pages `
  --temp-path .tmp\front-page-work
```

每个 `--temp-path` 都必须解析到项目 `.tmp/` 之下。无论验证成功或失败，显式临时路径都会在 `finally` 路径中清理。普通审计产物默认保留；`--prune-on-success` 只用于已经完成全部复核和配图处理后的显式打包副本。

### 5. 生成任务报告

所有试卷都完成最终验证或记录终态失败后，只运行一次：

```powershell
.\.venv\Scripts\python scripts\write_task_report.py `
  build\paper01\pipeline_report.json `
  build\paper02\pipeline_report.json `
  --output build\task-report.md
```

单份任务和批量任务都只能生成一份任务级 Markdown。

## 审批后统一配图

自动流水线仍先交付无图版本。报告列出预印图形 item 后，流程分成两个硬隔离阶段。

### 1. 图片准备阶段

每张候选图使用独立命令在原图同目录生成 `<原名>-clean.png`：

```powershell
.\.venv\Scripts\python scripts\prepare_clean_image.py D:\path\to\figure.png
```

默认阈值为 `195`，必要时可显式传入 `--threshold 1..254`。处理范围严格限定为：透明像素先铺到白底、整图转亮度、应用同一个全局阈值并输出纯黑白 RGB PNG。固定 PNG 编码使相同输入和参数产生稳定 SHA-256。若同名输出内容相同，命令返回 `unchanged`；若内容不同，则失败且绝不覆盖。

该命令不得裁切、缩放、旋转、局部擦除、修补、降噪重绘、补全结构或进行任何语义修改。这一阶段不得修改 qspec、TeX、PDF、`pipeline_report.json`、任务报告或正式发布文件，也不得从完成的答案图形中裁剪、清理或重建素材。输入只接受 PNG/JPG/JPEG，且不得把已有 `-clean` 文件再次作为输入。

同一卷全部 clean 图片由用户一次性确认。批准后建立 `prompt_image_binding.json`；manifest 不记录审批人、对话或自由文本：

```json
{
  "schema_version": 1,
  "approval_scope": "whole_paper",
  "items": [
    {
      "id": "7-3-1",
      "clean_path": "../../images/7-3-1-clean.png",
      "clean_sha256": "<64 lowercase hex>",
      "binding_asset_path": "../../images/7-3-1-clean.png",
      "binding_asset_sha256": "<64 lowercase hex>",
      "placement": {"mode": "default"}
    },
    {
      "id": "7-3-2",
      "clean_path": "../../images/7-3-2-clean.png",
      "clean_sha256": "<64 lowercase hex>",
      "binding_asset_path": "../../images/7-3-2-clean.png",
      "binding_asset_sha256": "<64 lowercase hex>",
      "placement": {
        "mode": "horizontal_repeat",
        "repeat_count": 3,
        "gap_mm": 0
      },
      "height_override": "52mm"
    }
  ]
}
```

旧版 manifest v1 继续兼容：`default` 保持原框高，`horizontal_repeat` 的 `repeat_count` 为 2–12，`gap_mm` 可为 `0`，clean 文件名必须以 `-clean.png` 结尾。

新任务使用 manifest v2。每个图片项必须声明 `asset_source: cleaned` 或 `asset_source: approved_original`；后者允许把用户明确批准的 JPG 确定性转换为最终绑定 PNG，但禁止去水印、清理或语义修改。`top_right` 和 `bottom_center` 可配 `height_ratio`（例如 `0.5`）及不小于 `0.6` 的 `clearance_mm`。顶层 `cancelled_visual_item_ids` 记录取消配图；`structural_changes` 只接受结构化 `merge_blocks` 或 `height_override`。连续块合并必须给出 question id、按原顺序相邻的 source ids、新 target id、kind 与 height。原始 qspec、AI layout、视觉需求均保留，执行后另写 `qspec.binding.yaml` 与调整后的视觉需求审计副本。

先运行只读闸门：

```powershell
.\.venv\Scripts\python scripts\bind_prompt_images.py check `
  prompt_image_binding.json `
  --qspec build\qspec.draft.yaml `
  --visual-requirements build\visual_requirements.json
```

题号未覆盖整卷、题号不属于需要配图或 uncertain item、文件缺失、未知字段或任一 SHA-256 不一致都会停止。clean 文件变化后必须更新哈希并重新整卷审批。

### 2. 获批执行阶段

闸门通过后，对同卷只运行一次：

```powershell
.\.venv\Scripts\python scripts\bind_prompt_images.py bind `
  prompt_image_binding.json `
  --qspec build\qspec.draft.yaml `
  --visual-requirements build\visual_requirements.json `
  --build-dir build `
  --formal-pdf build\answercard.pdf `
  --pipeline-report build\pipeline_report.json `
  --task-report build\task-report.md
```

脚本把获批资产复制到隔离工作区。若存在框高覆盖，它保留原 qspec，只写 `qspec.binding.yaml` 审计副本，并从这份既有无答案结构重新分页；随后渲染、XeLaTeX 编译、默认 `1.1 mm` 页框对齐、预览和最终验收。不会重新读取参考答案，也不会重跑结构提取或 AI 视觉判断。

默认和特殊布局都采用宽高双限制、保持纵横比、相对 A4 页面居中，并在四边至少保留 `0.6 mm`。非默认排列、重复数、间距和框高变化会进入 `pipeline_report.json` 与任务报告。

全部检查通过后，脚本才原子替换正式 PDF，写入 `embedded_visual_item_ids`，发布 `prompt_image_binding.json`、`qspec.binding.yaml`、绑定资产和预览，并清理成功临时目录。失败时正式 PDF 回滚或保持不变，安全诊断保留在 `build/binding-failures/`。

批量任务逐卷调用 `bind` 时不要传 `--task-report`；等所有卷绑定成功或失败后，仍只调用一次现有 `write_task_report.py` 聚合全部 `pipeline_report.json`。
