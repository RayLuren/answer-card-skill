# v0.4.0 工作流

1. 冻结第一层 PDF 的文件指纹。
2. 以 180 DPI 渲染所有整页 PNG。
3. 一个 fresh-context 视觉 worker 按页检查一整卷。
4. 接纳完整 `ready` 结果，或进入固定字段人工确认。
5. 人工确认后创建不可变 revision，由新上下文重新检查整卷。
6. 从 `ai_paper_spec.json` 机械生成 qspec v2 机器键和 visual manifest。
7. 整块分页、LaTeX、XeLaTeX、200 DPI 页框对齐、预览。
8. finalizer 验收并清理临时页面。
9. 所有卷终态后只写一次任务报告。

结构识别阶段没有 PDF 文本层、OCR、正则题号、小题过滤、叶子推断或脚本/AI 结构冲突审计。脚本只验证安全、字段类型、固定枚举、页码和可渲染高度。
