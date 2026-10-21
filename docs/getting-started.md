# 开始使用

v0.5.0 使用完整仓库源码：保留 `src/`、`scripts/`、`tex/`、`assets/`、`prompts/` 和 `spec/`，在仓库根目录运行下面的命令。首次使用按“宿主能力 → Python → TeX → 字体 → 样例实编译和看图”检查；已有可用环境直接复用。项目不提供跨平台自动安装器，也不随仓库分发字体。

## 1. 检查宿主能力

Agent 必须能读取仓库和用户指定的输入文件、写入输出及临时目录、执行本地命令，并直接查看完整页面图像。批处理还要求能在独立上下文中调度一个视觉 worker，让它按顺序检查一份试卷的全部页面，不继承其他任务的布局结论。

这些能力需按实际工具确认，不能只凭模型名称判断。缺少其中任何一项时，在处理参考答案前停止，以 `CAPABILITY_UNAVAILABLE` 说明缺少的能力。纯文本环境不能声称已完成视觉判断。能力要求的维护入口为 [SKILL.md](../SKILL.md)。

## 2. 准备 Python 环境

需要 Python 3.11+；缺少时从 [Python 官方网站](https://www.python.org/downloads/)安装适合当前系统的版本。所有 Python 依赖集中声明在 `pyproject.toml`，使用虚拟环境安装，无需另建 `requirements.txt`。项目不需要 PDF 文本提取库、OCR 或 ONNX Runtime。

Windows PowerShell：

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
```

macOS / Linux（先确认 `python3` 为 3.11+）：

```sh
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

已有 `.venv` 时先确认其 Python 版本和依赖，复用即可。后续命令使用该环境的 Python；下面以 Windows 路径举例，macOS / Linux 换成 `.venv/bin/python`。

## 3. 准备 XeLaTeX 和中文 TeX 包

先检查 `xelatex --version`，已有可用安装就复用。Windows 缺少 TeX 时使用 [MiKTeX 官方安装包](https://miktex.org/download)；其他系统由 Agent 根据系统选择官方 [TeX Live](https://tug.org/texlive/) 或 MiKTeX，并确认命令行可以找到 `xelatex`。

在样例编译前，通过 TeX 发行版的包管理器准备 `ctex`（含 `ctexart`）、`xeCJK`、`fontspec`，以及模板使用的 `geometry`、`array`、`enumitem`、`graphicx`、`tabularx`、`xcolor` 和它们的依赖。可用 `kpsewhich ctexart.cls`、`kpsewhich xeCJK.sty`、`kpsewhich fontspec.sty` 检查关键文件；缺包时让包管理器补齐。MiKTeX 的包管理和缺包设置见 [MiKTeX Console 官方说明](https://miktex.org/howto/miktex-console)。Python 的 `pip` 安装不会安装 TeX 发行版或 TeX 包。

## 4. 检查字体

模板按固定顺序选择当前环境可用的字体：

| 用途 | 优先顺序 |
| --- | --- |
| 中文 | `SimSun` → `Songti SC` → `Source Han Serif SC` → `Noto Serif CJK SC` |
| 西文 | `Times New Roman` → `TeX Gyre Termes` |

Mac 上的 `Songti SC`（宋体-简）与 `SimSun` 是不同字体；不能因购买地区假定某个字体已安装。若一行的候选均不可用，构建会明确报错。中文可从 [Adobe 思源宋体官方仓库](https://github.com/adobe-fonts/source-han-serif)安装简体中文 SC 常规体和粗体，或从 [Noto CJK 官方仓库](https://github.com/notofonts/noto-cjk)安装 `Noto Serif CJK SC` 常规体和粗体；西文可通过 TeX 包管理器准备 [TeX Gyre Termes](https://ctan.org/pkg/tex-gyre-termes)。安装后重新检查，再运行样例。不要用缺少标点或其他字形的改造、裁剪字体；模板会将缺字视为编译错误，需安装覆盖完整的对应字体后重试。

仓库不打包字体；不要从 Windows 字体目录复制 `SimSun` 或 `Times New Roman` 到公开仓库。字体文件的再分发和使用字体生成 PDF 是不同权限，见 [微软字体再分发说明](https://learn.microsoft.com/en-us/typography/fonts/font-faq#redistribution-and-extended-rights)。替代字体的字形和度量可能不同，需在下一步看图确认。

## 5. 生成并查看样例

使用已有的无答案样例 `spec/qspec.sample.yaml`，在新的构建子目录中编译并渲染，避免覆盖已有成品。下面的 `build/first-use-check` 如已存在，换成一个新的空目录，并同步调整两条命令的路径。

```powershell
.\.venv\Scripts\python scripts\build.py spec\qspec.sample.yaml --build-dir build\first-use-check
.\.venv\Scripts\python scripts\render_pages.py build\first-use-check\answercard.pdf build\first-use-check\pages
```

Agent 必须打开并检查全部样例页图：实际出现的中文与西文字形、字体样式、底部页码和正文布局均应正常，不能有缺字方框、乱码或越界；若使用带封面的规格，也检查封面。只有实编译成功且看图通过，才能说明本机基本构建环境可用；这不替代真实试卷的整卷视觉检查和最终验收。

代码测试单独通过唯一支持的入口运行：

```powershell
.\.venv\Scripts\python scripts\run_tests.py
```

测试会模拟部分编译行为，因此通过测试不能证明 XeLaTeX、字体或最终版面可用。

## 开始处理试卷

首次检查通过后创建批次：

```powershell
.\.venv\Scripts\python scripts\batch_pipeline.py prepare INPUT OUTPUT_ROOT
```

随后从 `status` 返回的 job 调度一个能查看全部页面的 fresh-context 视觉 worker。worker 只能写 `allowed_output_path`。用 `accept-ai-paper` 接纳；如等待人工确认，按固定请求生成确认 JSON 并用 `confirm-ai-paper` 开启新 revision。

完整命令和恢复规则见[用户指南](user-guide.md)。
