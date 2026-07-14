# AI 视觉 subagent 交接审计（历史记录）

审计日期：2026-07-14

本文件记录过渡期的交接审计结论，不是当前生产操作说明。现行合同已经改为严格 JSON job、隔离的 attempt 输出、fresh-context 整卷 worker 和主 Agent接纳；请读取 [`../references/codex-batch-orchestration.md`](../references/codex-batch-orchestration.md)。

仍然有效的审计结论：

- 视觉判断必须读取固定 prompt、answer-free outline、无猜测 skeleton 和原始逐页视觉证据。
- contact sheet、旧布局结论和页面文字正文都不是正式输入。
- 普通分辨率不足时，只重新打开源 PDF 或更高分辨率单页。
- outline 不得包含题型、高度、答案正文或每小题分值。
- 视觉输出必须使用严格白名单，不得包含自由说明、证据摘录或置信度字段。
- 主 Agent必须验证 schema、outline 覆盖、分值、百分比和安全字段后才能提升正式布局文件。

当前 worker 不再继承旧布局上下文、不再直接写正式布局文件，也不再依赖 Markdown 路径简报。每次可恢复失败都关闭旧线程；第二次尝试必须使用全新上下文。
