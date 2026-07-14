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

## 获准图片的后处理

当前自动流水线总是先生成无图版本。如果报告列出需要预印图形的 item，应交付初稿并等待用户提供单独管理的题面侧图片路径。

获得批准后，只编辑既有 `build/answercard.tex`，保留高度并替换匹配行：

```latex
% 修改前
\AnswerRow{7-3-1}{47.3mm}

% 修改后
\AnswerImageRow{7-3-1}{47.3mm}{../../images/38-23/7-3-1.png}
```

随后从 `build/` 直接编译，不重新运行结构提取、AI 判断、qspec 或分页：

```powershell
cd build
xelatex -interaction=nonstopmode -halt-on-error answercard.tex
cd ..
.\.venv\Scripts\python scripts\render_pages.py build\answercard.pdf build\pages
```

`\AnswerImageRow` 由模板统一实现：上下各保留 `0.6 mm`，保持纵横比，限制在答题区内，并相对整张 A4 页面水平居中。必须检查修改页及相邻页，然后记录已嵌入 item id 并重新生成任务报告。

自动 asset manifest 和行替换仍是后续工作；在该阶段落地前，不得把手工后处理描述为自动绑定。
