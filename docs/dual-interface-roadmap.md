# 人类界面与 AI Agent 界面建设路线图

> 历史路线说明：本文记录 v0.3.x 接口设想，尚未按 v0.4.0 整卷视觉契约完成独立架构评审，不得作为当前生产命令或数据合同。当前合同以 `README.md`、`docs/data-contracts.md` 和 `references/codex-batch-orchestration.md` 为准。

状态：长期路线图。Codex CLI 托管的批量 v1 已落地；通用人类界面和其他宿主仍需用户确认后实施。

## 当前项目所处阶段

当前项目已经提供一套面向工程开发的操作方式，以及一套初步的 AI Agent 操作方式。

已经具备的优势：

- Python 模块已经将 schema 校验、结构提取、AI 布局校验、分页、LaTeX 渲染、PDF 编译、边框对齐和页面预览等职责分开。
- `outline.json`、`ai_layout.json` 和 qspec 构成了可审计的结构化数据契约。
- CLI 辅助脚本既可以由开发者调用，也可以由 AI Agent 调用。
- PDF 页面预览为人工视觉验收提供了明确入口。
- 禁止泄露参考答案的安全边界已经写入项目规则，并有聚焦测试覆盖。

Codex v1 已补齐：

- `scripts/batch_pipeline.py` 提供目录级 prepare/status/accept/build/fail/report 产品入口。
- 不可变 manifest、原子 state、严格 JSON job 和 `run-report.json` 构成宿主无关边界。
- `SKILL.md` 是简洁产品入口，Codex 专属调度位于 `references/codex-batch-orchestration.md`。
- GitHub 默认首页已经改为中文，并提供结构一致的英文入口；详细使用、工作流、数据契约、验收和开发说明已拆分到 `docs/`。

仍存在的不足：

- `references/change-routing.md` 尚未创建。
- 尚未提供统一的环境与能力预检命令。
- 当前命令和示例偏向 Windows/PowerShell，跨平台调用方式尚未收敛。
- 已有 `pipeline_report.json`、`task-report.md` 和批处理 `run-report.json`，但未来统一 CLI/service 层仍需收敛稳定错误分类和通用机器输出。

## 核心设计原则

不要开发两套相互独立的业务实现。应当建设一个确定性核心，并在其上提供两套交互表面：

```text
人类图形界面 --------\
用户友好型 CLI -------+-> 应用服务层 -> 确定性的答题卡核心
AI Agent Skill -------+
未来 MCP 或 API ------/
```

面向人类的界面应重点优化：功能可发现性、视觉反馈、明确选项和人工确认。

面向 AI Agent 的界面应重点优化：能力发现、结构化输入输出、明确契约、稳定命令和可验证结果。

## 目标项目结构

```text
answer-card-skill/
├── README.md                     # 中文 GitHub 项目入口
├── README.en.md                  # 英文项目入口
├── SKILL.md                      # 面向 AI Agent 的工作流入口
├── CONTRIBUTING.md               # 开发与贡献规则
├── pyproject.toml
├── docs/
│   ├── README.md                 # 文档导航
│   ├── getting-started.md        # 安装和首次构建
│   ├── user-guide.md             # 单份、批量和配图后处理
│   ├── workflow.md               # 阶段边界和文件流转
│   ├── data-contracts.md         # 结构化数据契约
│   ├── validation-and-reporting.md
│   ├── development.md
│   ├── dual-interface-roadmap.md # 本路线图
│   └── history/                  # 非现行历史资料
├── references/
│   ├── change-routing.md         # AI 维护与定制需求路由
│   └── platform-compatibility.md # Agent 平台和模型/API 兼容说明
├── src/answercard/
│   ├── service.py                # 共享应用服务层
│   ├── cli.py                    # 统一命令行入口
│   ├── run_report.py             # 结构化运行状态与产物报告
│   ├── schema.py
│   ├── ai_layout_schema.py
│   ├── layout.py
│   ├── render_tex.py
│   └── frame_alignment.py
├── prompts/
├── tex/
├── spec/
├── tests/
└── ui/                           # 后期可选的人类界面
    └── local_web/
```

以上结构同时包含已经落地的文档层和未来代码方向。`change-routing.md`、`platform-compatibility.md`、service、统一 CLI 和可选 UI 仍应在对应阶段经过确认后再创建。

文档职责遵循一个权威来源原则：README 只提供入口和摘要，稳定的人类可读细节放在 `docs/`，Agent 执行合同放在 `SKILL.md` 与 `references/`。除中英文首页外，不建立整套逐文件翻译副本，以减少事实漂移。

## 共享应用服务层

应用服务层的 API 设计经过审查后，再考虑引入该层。它应向 CLI、未来图形界面、Agent Skill 适配器和未来 MCP 服务提供相同的确定性操作：

```python
def extract_structure(...): ...
def create_ai_layout_job(...): ...
def validate_ai_layout(...): ...
def generate_qspec(...): ...
def build_answer_card(...): ...
def render_previews(...): ...
def run_full_pipeline(...): ...
```

应用服务层必须调用现有领域模块，不能重复实现领域逻辑。现有辅助脚本可以逐步改造成应用服务层的轻量兼容包装器。

## 面向人类的操作界面

### 第一阶段：统一且用户友好的 CLI

提供一个具有清晰子命令的统一入口：

```text
answercard doctor
answercard inspect reference.pdf
answercard generate reference.pdf
answercard preview build/answercard.pdf
```

在正常使用过程中，用户不应被要求理解以下内部脚本之间的调用关系：

- `extract_outline.py`
- `batch_pipeline.py`
- `ai_layout_to_qspec.py`
- `build.py`
- `render_pages.py`

用户友好型 CLI 应提供：

- 清晰的阶段名称和执行进度；
- 可以直接采取行动的依赖错误提示；
- 在需要 AI 视觉判断或人工审核时明确暂停；
- 清楚显示生成产物的路径；
- 覆盖用户已有文件前进行确认；
- 确保消息、日志和运行报告中不出现参考答案内容。

### 后期阶段：可选的本地界面

未来可以考虑提供本地网页界面或桌面界面，主要流程可以包括：

1. 选择参考答案 PDF。
2. 显示提取出的无答案题目结构。
3. 审核 AI 判断的答题块类型和高度。
4. 进行规则允许范围内的人工调整。
5. 查看分页预览和页面边框对齐状态。
6. 生成最终空白答题卡。

图形界面必须调用共享应用服务层，不得在界面回调代码中重新实现结构提取、schema 校验、分页或渲染规则。

## 面向 AI Agent 的操作界面

### 正式化 `SKILL.md`

在 Skill 打包契约稳定后，为 `SKILL.md` 增加标准 Agent Skills frontmatter。正文应保持简洁，只保留：

- 核心工作流；
- 不可违反的安全边界；
- AI Agent 与视觉能力要求；
- 稳定的标准命令；
- 何时读取哪个 reference 文件的路由说明。

详细的数据契约和定制规则应放入 `references/`，仅在任务需要时由 AI 加载。

### 创建 `references/change-routing.md`

使用该文件将用户的自然语言需求转换为安全、明确的项目修改任务。文件应包含：

- 需求分类：单份文档调整、用户个性化定制、核心功能扩展、缺陷修复或禁止请求；
- 优先使用配置和模板覆盖，确有必要时才修改核心代码；
- 从用户需求到代码模块、测试、文档和产物检查的映射；
- 强制执行的答案泄露检查；
- 文档同步要求；
- 完成条件和停止条件。

### 增加机器可解析的命令输出

为稳定命令提供 `--json` 模式：

```text
answercard doctor --json
answercard validate-ai-layout build/ai_layout.json --json
answercard build spec/qspec.draft.yaml --json
```

结果格式示例：

```json
{
  "status": "success",
  "stage": "build",
  "artifacts": {
    "pdf": "build/answercard.pdf",
    "pages": 6
  },
  "warnings": [],
  "next_actions": [
    "inspect_page_previews"
  ]
}
```

稳定退出码应在跨平台兼容要求经过审查后再最终确定。可以从以下分类开始讨论：

```text
0  成功
2  输入或 schema 无效
3  缺少依赖
4  AI 布局判断尚未完成
5  PDF 编译失败
6  操作被安全边界拒绝
7  视觉验收尚未完成
```

### 增加能力发现入口

实现 `answercard doctor` 和 `answercard doctor --json`，检查以下项目：

- Python 版本和依赖；
- XeLaTeX 是否可用；
- PDF 页面预览渲染能力；
- 项目写入权限；
- AI 布局判断所需的视觉模型或视觉工具是否可用；
- 支持的 schema 版本；
- 可用模板；
- 当前流水线阶段以及可以继续使用的中间产物。

不能仅根据模型名称推断视觉能力。必须存在真实可用的图片检查路径；否则必须在 AI 布局判断前停止。

### 增加结构化运行报告

完整执行后，写入一份不包含答案内容的报告，例如 `build/run-report.json`：

```json
{
  "schema_version": 1,
  "status": "success",
  "completed_stages": [
    "outline",
    "ai_layout_validation",
    "qspec",
    "build",
    "preview"
  ],
  "artifacts": {},
  "warnings": [],
  "visual_review": {
    "required": true,
    "completed": true
  }
}
```

运行报告只能记录路径、状态、测量数据、警告和其他经过批准的结构元数据。严禁记录从参考答案中提取的正文、复制的方程、解答说明、最终答案或化学结构。

## 未来 MCP 或 API 层

下一阶段不必立即实现 MCP 服务。当稳定核心需要通过类型化工具支持多个 AI Agent 平台时，再考虑引入 MCP。

未来可能提供的工具：

```text
answercard.inspect_capabilities
answercard.extract_outline
answercard.create_ai_layout_job
answercard.validate_ai_layout
answercard.generate_qspec
answercard.build
answercard.render_previews
answercard.get_run_report
```

每个工具都应提供明确的输入和输出 schema。

AI 布局判断本身仍属于模型任务。确定性工具可以负责准备临时证据、验证结构化结果和执行后续流水线，但不能返回或持久化参考答案正文。

## 建议实施阶段

### 第一阶段：建立 AI Agent 导航

- 为 `SKILL.md` 确定最终的 Agent Skills frontmatter。
- 创建 `references/change-routing.md`。
- 数据契约的人类可读说明已经集中在 `docs/data-contracts.md`；只有 Agent 确实需要不同的机器执行合同且现有 schema/文档无法被简洁引用时，才创建额外 reference。
- 在 `SKILL.md` 中为每个 reference 文件写明明确的读取条件。
- 验证 Skill 包，并使用真实风格的用户请求进行前向测试。

### 第二阶段：统一工程入口

- 设计并新增 `src/answercard/service.py`。
- 设计并新增 `src/answercard/cli.py`。
- 在 `pyproject.toml` 中注册跨平台 `answercard` 控制台命令。
- 将现有辅助脚本逐步改造成轻量兼容包装器。
- 修改或移除任何现有命令契约前，先增加聚焦的 service 和 CLI 测试。

### 第三阶段：增加机器可观察性

- 增加 `answercard doctor --json`。
- 定义稳定退出码和结构化错误。
- 增加 `build/run-report.json`。
- 为能力发现、JSON 输出、错误映射和无答案运行报告增加测试。

### 第四阶段：改善人类操作界面

- 首先完善统一 CLI。
- 根据真实用户测试，再决定是否需要本地网页或桌面界面。
- 保持 qspec、AI layout、页面预览和边框对齐结果对用户可见并可审核。
- 要求图形界面使用与 AI Agent 界面相同的服务层和校验契约。

## 实施前需要确认的问题

1. 第一版面向人类的界面是否只需要统一 CLI，还是必须同时提供本地图形界面？
2. 哪些现有脚本必须保持向后兼容？
3. 用户个性化定制是否应存放在项目级配置和模板覆盖目录中？
4. 哪些命令应最先支持 `--json`？
5. 什么证据才能证明 AI Agent 已经实际完成视觉检查？
6. MCP 打包是否应等到 Agent Skills 和 CLI 契约经过前向测试之后？
7. 不同平台适配层应如何共享同一份权威 `SKILL.md`，避免内容分叉？

## 指导性结论

人类用户需要的是容易理解、视觉清晰、可以确认的操作界面。AI Agent 需要的是容易发现、结构化、可以验证、可以执行的操作界面。

因此，项目应逐步发展为：

```text
一个确定性核心
+ 一个共享应用服务层
+ 一个面向人类的操作入口
+ 一个面向 AI Agent 的操作入口
```

近期应优先建设 AI Agent 导航、统一 CLI/service 边界、能力发现和结构化运行报告。在这些基础稳定前，不宜优先投入独立图形界面或 MCP 服务的开发。
