# 开始使用

需要 Python 3.11+、PyMuPDF、Pillow、PyYAML、Jinja2 和可用的 XeLaTeX。项目不需要 PDF 文本提取库、OCR 或 ONNX Runtime。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python scripts\run_tests.py
```

创建批次：

```powershell
.\.venv\Scripts\python scripts\batch_pipeline.py prepare INPUT OUTPUT_ROOT
```

随后从 `status` 返回的 job 调度一个能查看全部页面的 fresh-context 视觉 worker。worker 只能写 `allowed_output_path`。用 `accept-ai-paper` 接纳；如等待人工确认，按固定请求生成确认 JSON 并用 `confirm-ai-paper` 开启新 revision。

完整命令和恢复规则见[用户指南](user-guide.md)。
