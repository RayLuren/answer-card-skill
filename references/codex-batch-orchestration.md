# Codex 批量调度合同

## 目录

1. 宿主边界
2. 准备与恢复
3. Job 合同
4. Worker 启动载荷
5. 并发与交错构建
6. 接纳与重试
7. 终态与报告
8. 安全持久化
9. 完成检查

## 1. 宿主边界

Python 核心只认识不可变 manifest、原子 state、严格 job、attempt 输出和确定性构建，不得引用 Codex 的线程、spawn、wait 或工具 API。Codex CLI 是 v1 唯一宿主；本文件是 Codex 适配层。

## 2. 准备与恢复

普通调用执行一次 `prepare INPUT OUTPUT_ROOT`，每次创建新的 `run-*` 目录。恢复只能显式引用已有 `batch_manifest.json`，不得重新 prepare 到旧 run。

`prepare` 只发现输入目录第一层 PDF，按文件名稳定排序，生成 `paper001` 起的内部 ID，固化文件名、字节数和 SHA-256。后续每个命令都通过 manifest 定位文件；源指纹变化直接以 `SOURCE_CHANGED` 终止该卷。

主 Agent在启动视觉 worker 前执行 `status`。若用户指定视觉并发数，使用该值；否则先读取宿主可用 agent 线程容量，为主 Agent预留一个槽位。无法可靠发现容量时最多安排 4 个视觉 worker。宿主槽位不足时把 job 留在队列中，不调用 `fail-paper`。

## 3. Job 合同

每次 attempt 读取对应的 `ai_layout_job.attempt-N.json`。Job 固定：

- batch、paper、attempt 标识；
- 固定 prompt、outline、skeleton、源 PDF、逐页 PNG 目录；
- 页数；
- 唯一 allowed output 路径 `ai_layout.attempt-N.json`。

worker 不得猜路径、改 manifest/state、写正式 `ai_layout.json`，也不得写其他说明、摘录或中间 JSON。主 Agent必须通过 `accept-ai-layout` 接纳 attempt；不得手工复制为正式文件。

## 4. Worker 启动载荷

为每卷启动一个 fresh-context subagent，并让它独占一整卷，不按页面或大题拆分。只传递：

1. 当前 job 的绝对路径；
2. 必须完整读取 job 中固定 prompt 的要求；
3. 只能写 allowed output 的限制；
4. 禁止持久化或复述答案内容的安全边界；
5. attempt 计时命令。

不要传递旧 attempt 的布局结论、失败正文、自由视觉说明或主 Agent的推测。worker 在自己的 per-paper `pipeline_report.json` 中启动 `ai_layout_judgment_attempt_N`。只有 allowed output 写入并自检通过后才用默认 `passed` 停止；若因结构冲突、能力不足或工具中断而没有产出，必须用 `stop --status failed --code FIXED_CODE` 结束，固定码不得包含答案或自由描述。如果某项首次判断为 `unknown`，在同一 worker 内显式重看原页一次；仍不确定时使用合同规定的 `unknown`、`95mm` 和 fallback 标志。这不是整卷重试。

## 5. 并发与交错构建

维护一个有界视觉队列：

1. 空槽位领取下一份 awaiting job。
2. worker 完成后立即释放槽位，让下一卷开始。
3. 主 Agent随即运行 `accept-ai-layout`。
4. 接纳成功的卷立即进入单卷 `build --paper`，不等待其他视觉 worker。
5. 本地 XeLaTeX 构建始终串行；视觉 worker 可在构建期间继续并行。

任何 subagent 结束后都关闭旧线程。重试必须创建新 fresh context，不能继续旧线程。

## 6. 接纳与重试

`accept-ai-layout` 依次检查 allowed output 路径、JSON、严格 schema、安全字段、outline 覆盖、分值、百分比和 fallback 合同。通过后才原子生成正式 `ai_layout.json`。

首次出现无效 JSON、schema 失败、工具中断或临时证据读取失败时，关闭旧线程，读取 attempt 2 job，并在全新上下文中重试 exactly once。第二次可恢复失败以 `AI_RETRY_EXHAUSTED` 终止。

结构冲突、源变化、视觉能力不足或安全拒绝不重试。调用 `fail-paper` 时只传固定 code，不传页面正文或异常原文。

## 7. 终态与报告

`build` 只处理 `ai_layout_valid`；跳过 `validated` 和 `failed`，因此恢复调用不会重建终态卷。finalizer 成功后，发布 PDF 到 run 根目录，并把审计产物归档到 `audit/paperNNN/`。失败卷进入 `failed/paperNNN/`。两条路径都必须清理临时源页证据。

当且仅当全部卷达到 `validated` 或 `failed`，调用一次 `report`。它生成一份 `task-report.md` 和一份 `run-report.json`。重复调用返回现有文件。部分失败不得阻止其他成功 PDF 发布或阻止终态总报告。

## 8. 安全持久化

允许持久化结构 ID、题型、高度、固定视觉类别、固定错误 code、计时、产物路径和校验结果。禁止持久化源页文字、答案、解答、方程正文、化学结构正文、free-form reason、visual description 或未经清洗的异常消息。无效 attempt 输出必须立即删除。

第一版只交付无图初版与配图需求。不要自动绑定图片，不要从答案图重建题面图。

## 9. 完成检查

- 根目录成功 PDF 数等于 `run-report.json.success_count`。
- 每个输入在 run report 中恰有一个终态。
- `task-report.md` 和 `run-report.json` 各只有一份。
- 成功审计目录与失败目录互斥。
- `.tmp/batches/<batch-id>/` 不再保留已终态卷的源页。
- 没有 worker 直接写正式 `ai_layout.json`。
- 没有自动图片绑定或第二次成品 PDF AI 复核。
