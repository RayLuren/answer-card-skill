# 开发指南

[返回文档导航](README.md)

项目将结构提取、schema、AI 判断、分页、LaTeX 渲染、PDF 编译、预览和验收保持为可独立检查的模块。新增功能应复用这些边界，不在脚本或界面中复制业务逻辑。

## 项目结构

```text
answer-card-skill/
├── assets/                     # Skill 自带的首页素材
├── docs/                       # 面向用户和维护者的专题文档
├── prompts/                    # 固定 AI 判断 prompt
├── references/                 # Agent 按需读取的执行合同
├── scripts/                    # CLI 风格入口和流水线包装器
├── spec/                       # 手写 sample 和本地生成的 qspec
├── src/answercard/             # Python 核心模块
├── tests/                      # 聚焦测试
├── tex/                        # Jinja2/LaTeX 模板
├── CHANGELOG.md                # 版本、发布日期和用户可见变化
├── README.md                   # 中文项目首页
├── README.en.md                # 英文项目首页
├── SKILL.md                    # AI Agent 简明入口
└── pyproject.toml
```

本地 `fixtures/`、`build/`、`.tmp/` 和虚拟环境不属于发布产物。

## 支持的测试入口

只能运行：

```powershell
.\.venv\Scripts\python scripts\run_tests.py
```

不要直接复用 pytest 默认临时目录，也不要把 `--basetemp` 指向项目的 `build/` 或 `.tmp/`。包装器会创建独立的系统临时目录，并使清理失败可见。

行为变更必须增加聚焦测试。涉及渲染的测试不能依赖真实参考答案内容；测试字符串只允许使用短小、人工构造且不构成答案的示例。

## 开发原则

- 变更范围保持窄小、确定和可审计。
- 优先使用结构化解析和显式 schema，避免临时文本拼接。
- 保留人工可审查的中间规格，不把 PDF 渲染器当作数据模型。
- 生成答题卡只包含结构、标签、答题框和计分元数据。
- outline 不承担题型、高度或答案空间判断。
- AI layout 只能使用固定白名单字段。
- 分页以完整 block 为单位，不跨页拆分。计算顺序固定为“qspec 框高 + 实际横线宽度 + 当前位置题号标题行高 → 30% 阈值决策”；不得恢复为统一的每框经验开销。
- 页框对齐修正必须落实到 item 级高度并重新调用共享分页核心；分页成员改变后不得沿用旧的页序号顶部补偿。
- 失败时保留安全诊断，终态后清理瞬时参考证据。
- 生成物、缓存、虚拟环境、fixture 和 package metadata 不进入 Git。

## 答案安全边界

任何实现都不得复制、摘要、改写、渲染、记录或测试答案正文、最终答案、解释、答案键或完成的答案图形。

结构提取仅允许持久化题号、章节、主问题分值和页码。AI 视觉判断可以瞬时查看原始页面以估计答题形状，但输出只允许固定结构标签和尺寸。

需要预印图形时，先分类“是否需要”，不要从答案 PDF 提取图片。实际资产必须来自题目卷或其他人工批准的题面侧来源。

## 模块边界

| 职责 | 模块 |
| --- | --- |
| qspec schema | `src/answercard/schema.py` |
| outline 提取 | `src/answercard/extract_outline.py` |
| skeleton | `src/answercard/ai_layout_skeleton.py` |
| AI layout schema/审计 | `src/answercard/ai_layout_schema.py`、`ai_layout_audit.py` |
| 配图需求 | `src/answercard/visual_requirements.py` |
| qspec 转换 | `src/answercard/ai_layout_to_qspec.py` |
| 分页 | `src/answercard/layout.py` |
| LaTeX 渲染 | `src/answercard/render_tex.py` |
| 页框对齐 | `src/answercard/frame_alignment.py` |
| 计时与报告 | `pipeline_timing.py`、`task_report.py` |
| 批处理状态 | `src/answercard/batch.py` |

脚本应尽量作为这些模块的轻量入口。未来 CLI、GUI 或 API 必须调用共享核心，不能重新实现 schema、分页或安全规则。

## Windows 跨盘符

当工程输出和首页资源位于不同盘符时，`render_tex.py` 使用绝对正斜杠资源路径；同盘时优先使用相对路径。修改路径逻辑时必须保留这项回归测试。

## 文档维护

- `README.md` 是中文 GitHub 首页，`README.en.md` 是结构一致的英文入口。
- `docs/` 保存用户可阅读的稳定说明、开发文档和路线图。
- `references/` 保存 AI Agent 只在相关任务中读取的详细合同。
- `SKILL.md` 保持简洁，只包含安全边界、生产入口、重试停止规则和稳定命令。
- 历史资料放在 `docs/history/`，必须标记“非现行规范”。
- 操作流程变更时同步主 README 中的 Mermaid、相关专题文档和外层 `AGENTS.md`。
- 不在多个文件复制完整协议；选择一个权威位置，其他位置只做摘要和链接。

## 版本与发布

项目使用语义化版本，当前版本为 `v0.3.0`。`0.x` 阶段按以下规则递增：

- 补丁版本（例如 `0.1.1`）：兼容的错误修复和小范围调整。
- 次版本（例如 `0.2.0`）：新增兼容功能；`0.x` 阶段如发生不兼容的生产契约或工作流变化，也必须提升次版本并在变更日志中突出说明。
- `1.0.0`：生产契约、接口和发布流程稳定后再发布。

每项尚未发布的用户可见变化先写入 `CHANGELOG.md` 的 `[Unreleased]`。正式发布时必须同时：

1. 将变化归入带 `YYYY-MM-DD` 日期的版本标题。
2. 同步 `pyproject.toml`、`src/answercard/__init__.py`、版本测试和中英文 README。
3. 完成发布提交后创建同名 Git 标签，例如 `v0.2.0`；标签不得提前指向未提交工作树，也不得移动已发布标签。
4. 纯文字勘误可以保留在 `[Unreleased]`，不要求每次编辑立即升级版本。

开发工作树可以提前把代码版本字段设置为下一目标版本，但 README 和变更日志必须明确标为“待发布”；在发布提交和标签完成之前，不得填写或暗示正式发布日期。

## 发布前最低检查

1. 运行受支持的完整测试入口。
2. 运行 `git diff --check`。
3. 检查所有相对 Markdown 链接指向已跟踪文件。
4. 确认 `fixtures/`、`build/`、`.tmp/`、虚拟环境、缓存和 `*.egg-info/` 未被跟踪。
5. 搜索文档中是否存在本地绝对输入路径、参考答案内容或过时命令。
6. 确认中文和英文 README 相互链接，关键版本、默认容差和安全说明一致。
7. 确认版本字段、README、`CHANGELOG.md` 的版本号和发布日期一致；发布提交完成后再创建 Git 标签。
8. 正式公开前确认许可证、仓库可见性和发布范围。
