# Codex 整卷视觉批处理编排

本文描述 Codex host 如何并发调度视觉 worker；Python 核心不依赖任何线程 API。

## 准备

普通调用只运行一次 `prepare INPUT OUTPUT_ROOT`。每次生成不可覆盖的 `run-*`，冻结来源文件名、大小和 SHA-256。恢复必须显式使用已有 `batch_manifest.json`。

`prepare` 只渲染 180 DPI 的整页 PNG，不提取 PDF 文字、不运行 OCR、不匹配题号、不生成 outline 或 skeleton。页面必须按 `page-001.png` 至末页完整存在。

## bounded concurrency

视觉阶段采用 bounded concurrency。每个 fresh-context worker 负责 one whole paper，不能按页面或大题拆分。槽位不足时只排队，不得把试卷标记失败。确定性 PDF 构建始终串行。

Worker 每次只读取：

- `ai_paper_job.revision-R.attempt-N.json`
- 固定 `prompts/ai_paper_visual_extract.md`
- job 指定的全部页面和必要时的原 PDF 局部放大
- job 指定的严格人工确认 JSON（如有）

Worker 只能写 `allowed_output_path`，不得修改 manifest、state、正式 `ai_paper_spec.json` 或其他文件。不得输出说明、摘录或中间 JSON。

## 接纳和重试

主 Agent运行 `accept-ai-paper`。它只检查 JSON、安全字段、固定枚举、页码、高度和可渲染性，不与 OCR、outline、正则或另一模型比对，也不检查显示题号的重复、连续和层级。

无效 JSON、schema/安全失败、输出缺失或工具中断会删除无效 attempt，并创建一次不继承旧结论的 fresh-context attempt 2。第二次失败进入 `AI_RETRY_EXHAUSTED`。

单题 `unknown` 的显式复看发生在同一个 worker 内；若仍不确定使用 95mm fallback。This does not count as the whole-paper retry.

## 人工确认 revision

`needs_human_review` 不是失败，也不消耗 attempt 2。主 Agent不得把候选值自行拼接成正式结构。

1. 向用户展示固定 review id、页码、区域、目标和候选值。
2. 用户文件必须一一覆盖当前 review id。
3. 运行 `confirm-ai-paper` 冻结 `human_confirmation.revision-R.json`。
4. 创建 attempt 1 的新 revision job。
5. 新 fresh-context worker 重新检查整卷，而不是修补旧草稿。

来源 PDF 指纹变化会使全部旧确认失效并终止该卷。

## 构建和归档

`build` 只接受 `ai_paper_valid`。它从正式 `ai_paper_spec.json` 生成 qspec v2 和 visual manifest，随后分页、XeLaTeX、200 DPI 页框测量、默认 1.1 mm 对齐、预览和 finalizer。

成功后 PDF 原子发布到 run 根目录，审计文件进入 `audit/paperNNN/`；失败诊断进入 `failed/paperNNN/`。两条终态路径都清理临时源页。等待人工确认期间必须保留页面证据以便新 revision 重看。

当且仅当所有卷为 `validated` 或 `failed` 时运行 `report` exactly once。重复调用返回已有正式报告。等待人工确认的卷可由 `status` 查看，但不得提前生成正式 task report。

## 命令

```powershell
python scripts/batch_pipeline.py prepare INPUT OUTPUT_ROOT
python scripts/batch_pipeline.py status RUN\batch_manifest.json
python scripts/batch_pipeline.py accept-ai-paper RUN\batch_manifest.json PAPER_ID ATTEMPT_JSON
python scripts/batch_pipeline.py confirm-ai-paper RUN\batch_manifest.json PAPER_ID CONFIRMATION_JSON
python scripts/batch_pipeline.py build RUN\batch_manifest.json --paper PAPER_ID
python scripts/batch_pipeline.py fail-paper RUN\batch_manifest.json PAPER_ID --code CODE
python scripts/batch_pipeline.py report RUN\batch_manifest.json
```

Keep the default three correction passes unless the retained answer-free history demonstrates slow convergence. A bounded rebuild may use `--max-alignment-passes 4`; retain both the configured and default limits in the report, and keep the tolerance at `1.1mm`.

视觉能力缺失使用 `CAPABILITY_UNAVAILABLE`。不得以纯文本推测代替视觉检查。
