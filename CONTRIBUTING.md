# 贡献指南

感谢你改进 `answer-card-skill`。项目仍处于工程契约收敛阶段，请优先提交范围清晰、可验证且不改变答案安全边界的变更。

## 开始之前

1. 阅读[开发指南](docs/development.md)。
2. 涉及数据文件时阅读[数据契约](docs/data-contracts.md)。
3. 涉及流水线或报告时阅读[工作流说明](docs/workflow.md)和[验收与报告](docs/validation-and-reporting.md)。
4. 不要在 issue、提交、测试、日志或文档中粘贴参考答案内容。

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python scripts\run_tests.py
```

测试必须通过 `scripts/run_tests.py` 运行。不要将 pytest 临时目录放在仓库内。

## 变更要求

- 保持变更聚焦，不顺手重构无关模块。
- 行为变化增加聚焦测试。
- schema 变化必须同步校验器、示例、转换、报告和文档。
- 流水线变化必须同步主 README 的 Mermaid、专题文档和 Agent 操作规则。
- 新的输出字段必须是固定、答案无关且可审计的结构数据。
- 不提交 `fixtures/`、`build/`、`.tmp/`、虚拟环境、缓存或 package metadata。

## 提交前检查

```powershell
.\.venv\Scripts\python scripts\run_tests.py
git diff --check
git status --short
```

同时检查：

- Markdown 相对链接有效。
- 中英文 README 的关键安全规则和默认值一致。
- 没有参考答案正文、最终答案、解释或答案图形进入 Git diff。
- 新增文件都属于预期发布范围。

## Pull Request 建议

PR 描述应说明：

- 解决的问题
- 采用的实现边界
- 新增或更新的测试
- 对 schema、PDF 视觉结果、报告和兼容性的影响
- 是否需要人工预览验收

不要在 PR 描述中附带真实参考答案内容或临时页面证据。
