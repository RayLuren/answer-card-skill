# 开发说明

核心模块：

- `ai_paper_schema.py`：整卷 AI、安全和人工确认 schema。
- `ai_paper_to_qspec.py`：qspec v2 稳定机器键。
- `batch.py` / `batch_pipeline.py`：不可变 manifest、revision 和状态机。
- `visual_requirements.py`：v2 配图投影及 v1 读取兼容。
- `schema.py`：qspec v1/v2 读取。
- `layout.py` / `render_tex.py`：确定性分页和显示题号渲染。
- `finalize_pipeline.py`：最终验收与清理。

生产代码不得新增 PDF 文字提取、OCR、正则结构候选或显示题号合理性检查。结构判断规则只能放在固定视觉 prompt；安全和可渲染性规则放在 schema。

所有测试使用 `python scripts/run_tests.py`。改动数据合同必须同时更新中英文 README、项目 Skill、数据契约和编排参考。
