# 验收与报告

[返回文档导航](README.md)

最终 PDF 只有通过确定性的产物门禁后才能视为正确导出。视觉外观检查仍通过逐页预览完成，但结构、页数、几何、日志和页框测量不得依赖人工口头判断。

## 页框对齐

启用对齐时，`src/answercard/frame_alignment.py` 以 `200 DPI` 将 PDF 光栅化，扫描每页第一行和最后一行满足条件的水平深色框线。

- 默认容差：`1.1 mm`
- 默认最大修正次数：3
- `pass 0`：首次编译结果，不占用修正次数
- 检查对象：除最终正文页外的答题区页面边缘
- 结果文件：`build/frame_alignment.json`

`200 DPI` 的名义最小单位为 `25.4 / 200 = 0.127 mm`。受 A4 光栅舍入影响，观测步长约为 `0.12698 mm`；因此八像素差约为 `1.016 mm`，可通过 `1.1 mm` 标准，九像素差约为 `1.143 mm`，不能通过。

如经审查需要例外，可显式传入 `--alignment-tolerance-mm` 或 `--max-alignment-passes`。实际值和默认值都进入报告；非默认设置必须在任务 Markdown 中显式披露。finalize 使用的容差必须与编译阶段一致。

## 最终验证门

典型调用：

```powershell
.\.venv\Scripts\python scripts\finalize_pipeline.py `
  --front-pages 1 `
  --temp-path .tmp\source-pages `
  --temp-path .tmp\front-page-work
```

finalizer 检查：

1. qspec 能通过严格 schema 加载。
2. `visual_requirements.json` 能通过严格校验并精确覆盖所有 qspec block。
3. PDF 页数等于规划正文页数加 `--front-pages`。
4. 每个最终页面都是 A4。
5. PDF 可提取文本不包含被禁止的答案键短语。
6. 至少存在一份编译日志，且没有受禁止的 fatal、emergency、LaTeX 或 overfull-vbox 标记。
7. 最终页框报告覆盖所有正文页，并满足配置的容差。
8. 预览非空、编号连续，并与 PDF 页数完全一致。
9. 生成的 LaTeX 保留每页底部居中页码，并用 `\QuestionTitleFont` 渲染页码数字。

显式临时路径只能位于项目 `.tmp/` 下，并且无论验证成功或失败都在 `finally` 中清理。失败时保留诊断；成功时默认保留 outline、AI layout、qspec、LaTeX、日志、视觉需求、对齐记录、报告、PDF 和预览。

`--prune-on-success` 不属于普通生产验收。只有完成全部人工复核和图片后处理后，才可对单独的打包副本使用。

## `pipeline_report.json`

单份试卷报告包含：

- 每个阶段的状态和耗时
- 总墙钟时间
- 预期与实际页数
- 预览数量
- 页框顶部/底部 spread
- 实际和默认对齐容差
- 最大修正次数
- `pass 0` 和每次修正的无答案历史
- AI layout 与 outline 的结构冲突
- 印刷百分比实际总和
- `unknown` 95mm fallback item id
- 需要预印图形和不确定图形的 item id
- 清理及可选 pruning 状态

报告不能包含源页面文字、答案、自由视觉描述或答案图形。

## 任务级 Markdown

所有试卷都通过 finalization 或记录终态失败后，调用 `scripts/write_task_report.py` 一次。单份任务和批量任务都只有一个 Markdown 报告。

```powershell
.\.venv\Scripts\python scripts\write_task_report.py `
  build\paper01\pipeline_report.json `
  build\paper02\pipeline_report.json `
  --output build\task-report.md
```

报告开头必须是 `## 一分钟总览`，并列出：

- 每份仍需图片的试卷及 item id
- 单独列出的不确定视觉案例
- 每份未正确导出的试卷及近似失败原因
- 页框失败时的最终顶部/底部 spread、适用标准和剩余超标毫米数

通过和失败的试卷使用相同配图披露规则。如果 finalization 在把视觉详情写入 pipeline report 前停止，生成器会校验并读取相邻 `visual_requirements.json`；只有两者都不可用时才显示明显警告，不能静默报告“无需图片”。

详细部分必须列出每个阶段耗时、失败或重试、非默认参数、所有结构冲突、非 100 的印刷百分比总和和所有第二次复查仍使用的 `unknown` fallback。

页框失败时必须增加 `### 页框对齐未通过明细`，展示 `pass 0`、每次修正、顶部/底部 spread、标准、每次通过状态和最终结论。较旧报告缺少历史时，可以从相邻 `frame_alignment.json` 确定性补充，不能修改源报告。

## 计时

新任务开始：

```powershell
.\.venv\Scripts\python scripts\pipeline_timer.py begin --label "paper-name"
```

Agent 执行视觉检查前后：

```powershell
.\.venv\Scripts\python scripts\pipeline_timer.py start ai_layout_judgment
# 执行视觉检查并验证 ai_layout.json
.\.venv\Scripts\python scripts\pipeline_timer.py stop ai_layout_judgment
```

查看当前汇总：

```powershell
.\.venv\Scripts\python scripts\pipeline_timer.py summary
```

计时使用墙钟时间，因此包括图片加载和工具等待，但不声称测量模型私有推理时间。计时只发生在主要阶段边界，不能存储自由文本证据或答案内容。
