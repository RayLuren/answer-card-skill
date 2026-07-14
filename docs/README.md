# 项目文档导航

[返回中文首页](../README.md) | [English README](../README.en.md)

本文档目录按读者角色组织。项目首页只保留概览和最短使用路径；稳定的技术细节放在专题文档中，AI Agent 的强制执行合同放在 `SKILL.md` 与 `references/` 中。

## 我只想生成答题卡

1. 阅读[快速开始](getting-started.md)，安装 Python、XeLaTeX 和页面预览依赖。
2. 阅读[使用指南](user-guide.md)，选择单份工程流程或 Codex 托管的目录批处理流程。
3. 通过[验收与报告](validation-and-reporting.md)了解最终 PDF、预览和任务报告的通过标准。

## 我想理解项目如何工作

- [工作流说明](workflow.md)：阶段边界、受控反馈环和主要文件。
- [数据契约](data-contracts.md)：`outline.json`、`ai_layout.json`、`visual_requirements.json` 和 qspec。
- [人类界面与 AI Agent 界面建设路线图](dual-interface-roadmap.md)：长期架构方向和待确认问题。

## 我要开发或维护项目

- [开发指南](development.md)：目录结构、测试入口、跨盘符行为和安全开发边界。
- [贡献指南](../CONTRIBUTING.md)：提交范围、测试和文档同步要求。
- [Codex 批量调度合同](../references/codex-batch-orchestration.md)：Codex worker、并发、重试和主 Agent 接纳规则。
- `SKILL.md`：面向 AI Agent 的最短产品入口。

## 历史资料

- [AI 视觉 subagent 交接审计](history/ai-layout-subagent-handoff-audit.md)：仅记录过渡期审计结论，不是现行生产说明。

历史文档必须显式标明状态，并链接到替代它的现行合同。不得从历史文档恢复已经废弃的工作流。
