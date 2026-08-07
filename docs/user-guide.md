# 用户指南

## 批处理

```powershell
python scripts/batch_pipeline.py prepare INPUT OUTPUT_ROOT
python scripts/batch_pipeline.py status RUN\batch_manifest.json
python scripts/batch_pipeline.py accept-ai-paper RUN\batch_manifest.json PAPER_ID ATTEMPT_JSON
python scripts/batch_pipeline.py confirm-ai-paper RUN\batch_manifest.json PAPER_ID CONFIRMATION_JSON
python scripts/batch_pipeline.py build RUN\batch_manifest.json --paper PAPER_ID
python scripts/batch_pipeline.py report RUN\batch_manifest.json
```

视觉 job 指定固定 prompt、全部页面、页数、可选确认文件和唯一输出路径。不要给 worker 旧 attempt、自由对话、OCR、页面文字或主 Agent 的题号猜测。

`ready` 才能构建。`needs_human_review` 的确认文件示例：

```json
{
  "schema_version": 1,
  "paper_id": "paper001",
  "revision": 1,
  "decisions": [{"review_id": "r001", "value": "7"}]
}
```

确认值不会被脚本直接拼入 qspec；它只成为新上下文整卷重检的输入。

## 配图

首次交付仍是无图版。只使用用户批准的题面侧资产；绑定清单使用 qspec v2 的机器 `item_id`，报告显示 AI `display_id`。清图限制和原子发布规则保持不变。

## 验证

最终验收检查 ready AI 契约、qspec、visual 覆盖、A4、页数、底部页码、编译日志、200 DPI/1.1 mm 页框对齐和预览数量，并清理显式临时页面路径。
