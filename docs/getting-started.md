# 快速开始

[返回文档导航](README.md)

本页用于完成环境安装、依赖检查和第一次示例构建。生产批处理和中断恢复见[使用指南](user-guide.md)。

## 1. 环境要求

- Python 3.11+
- Git
- XeLaTeX，且 `xelatex` 可以从命令行直接调用
- Python 包以 `pyproject.toml` 为准，其中 PyMuPDF 用于页面渲染，`rapidocr-onnxruntime` 用于无文字层页面的临时 OCR
- 生产 AI 布局阶段还需要能够直接查看页面图片的视觉模型或可信视觉工具

项目的确定性阶段可以在没有 AI 的情况下运行，但文本模型不得替代视觉判断或声称视觉判断已经完成。

## 2. 获取项目

Windows PowerShell：

```powershell
git clone https://github.com/RayLuren/answer-card-skill.git
cd answer-card-skill
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e .
```

Linux 或 macOS 可将虚拟环境解释器替换为 `.venv/bin/python`。当前文档和前向测试主要覆盖 Windows；其他平台仍需进一步验证。

## 3. 检查外部命令

```powershell
.\.venv\Scripts\python --version
xelatex --version
```

如果 `xelatex` 不存在，请安装 TeX Live、MiKTeX 或其他提供 XeLaTeX 的 TeX 发行版，并确认安装目录已加入 `PATH`。

## 4. 运行项目测试

只使用项目提供的测试入口：

```powershell
.\.venv\Scripts\python scripts\run_tests.py
```

该脚本在操作系统临时目录中为每次 pytest 执行创建独立 GUID 目录，并在 `finally` 路径中清理。测试失败和清理失败都会明确返回非零状态。不要将 pytest `--basetemp` 指向项目的 `build/` 或 `.tmp/`。

## 5. 构建内置示例

从项目根目录执行：

```powershell
.\.venv\Scripts\python scripts\render_tex.py spec\qspec.sample.yaml build\answercard.tex
.\.venv\Scripts\python scripts\build.py spec\qspec.sample.yaml
.\.venv\Scripts\python scripts\render_pages.py build\answercard.pdf build\pages
```

成功后主要产物为：

```text
build/
├── answercard.tex
├── answercard.pdf
├── build.log
└── pages/
    ├── page-001.png
    └── ...
```

页面预览名称从 `page-001.png` 开始，按一页一个文件稳定编号。

## 6. 下一步

- 处理真实的单份参考 PDF：阅读[使用指南：单份工程流程](user-guide.md#单份工程流程)。
- 处理一个目录：阅读[使用指南：Codex 托管批处理](user-guide.md#codex-托管批处理)。
- 理解各 JSON/YAML 文件：阅读[数据契约](data-contracts.md)。
- 检查最终交付标准：阅读[验收与报告](validation-and-reporting.md)。

## 常见问题

### 找不到 XeLaTeX

`scripts/build.py` 会给出需要安装 TeX 发行版或修复 `PATH` 的提示。编译失败的捕获输出会写入 `build/build.log`。

### 找不到 PyMuPDF

安装页面预览依赖：

```powershell
.\.venv\Scripts\python -m pip install pymupdf
```

### 无文字层 PDF 无法提取结构

默认提取器先用 PyMuPDF 快速探测全部页面，只让 `pypdf` 处理有文字层的页面；空白文字层页面才会以 `220 DPI` 在内存中渲染并调用 RapidOCR。探测文字、OCR 全文和 OCR 页面图片都不会写盘，只会把题号、总分和来源页等允许字段写入 `outline.json`。如果依赖缺失，请重新执行：

```powershell
.\.venv\Scripts\python -m pip install -e .
```

### 项目与系统临时目录不在同一盘符

这是受支持的 Windows 场景。渲染器会在跨盘符时对首页资源使用绝对正斜杠路径，同盘时优先使用相对路径。
