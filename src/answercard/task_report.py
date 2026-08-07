"""Create one user-facing Markdown report for one answer-card task."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from answercard.frame_alignment import (
    DEFAULT_ALIGNMENT_TOLERANCE_MM,
    DEFAULT_MAX_ALIGNMENT_PASSES,
    load_alignment_pass_summaries,
)
from answercard.visual_requirements import (
    load_visual_requirements,
    visual_requirement_report_data,
)


DEFAULT_TASK_REPORT_TITLE = "答题卡生成任务汇报"
_FORBIDDEN_LABEL_TERMS = ("参考答案", "答案及评分标准")
_VISUAL_REQUIREMENT_LABELS = {
    "modify_existing_visual": "在既有图上标记或连线",
    "complete_existing_visual": "补全既有图形",
    "draw_on_scaffold": "在预置框架上作图",
    "uncertain": "待视觉复核",
}
_VISUAL_TYPE_LABELS = {
    "chemical_structure": "化学结构",
    "diagram": "示意图",
    "coordinate_system": "坐标系",
    "table": "表格",
    "grid": "网格",
    "reaction_framework": "反应框架",
    "flowchart": "流程图",
    "apparatus": "实验装置",
    "other": "其他图形",
    "uncertain": "待确认",
}
_STAGE_LABELS = {
    "render_source_pages": "渲染整卷视觉证据",
    "validate_ai_paper_spec": "校验整卷视觉 AI 结果",
    "require_ready_ai_paper": "确认人工复核已关闭",
    "ai_paper_to_qspec": "生成并校验 qspec v2",
    "ai_layout_judgment": "AI 版面判断",
    "ai_layout_validation": "AI 布局校验",
    "build_answer_card": "生成 LaTeX、编译 PDF 与页框对齐",
    "build_alignment_retry": "页框对齐重试",
    "render_pdf_pages": "渲染页面预览",
    "render_and_sanity_retry": "预览渲染与完整性重试",
    "artifact_sanity": "产物完整性检查",
    "validate_qspec": "最终 qspec 校验",
    "plan_expected_body_pages": "核对正文页数计划",
    "validate_pdf": "最终 PDF 校验",
    "validate_compile_logs": "编译日志校验",
    "validate_alignment_report": "页框对齐报告校验",
    "validate_previews": "页面预览校验",
    "cleanup_temporary_artifacts": "清理临时证据",
    "prune_build_artifacts": "裁剪构建目录",
    "bind_prompt_images_build": "审批后统一配图重建与页框对齐",
    "bind_prompt_images_render_pages": "审批后配图页面预览",
}


def write_task_report(
    report_paths: Iterable[str | Path],
    output_path: str | Path,
    *,
    title: str = DEFAULT_TASK_REPORT_TITLE,
) -> Path:
    """Write one Markdown report aggregating one or more pipeline reports."""

    reports = [_load_report(Path(path)) for path in report_paths]
    if not reports:
        raise ValueError("at least one pipeline report is required")

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        render_task_report(reports, title=title),
        encoding="utf-8",
        newline="\n",
    )
    return destination


def render_task_report(
    reports: list[dict[str, Any]],
    *,
    title: str = DEFAULT_TASK_REPORT_TITLE,
) -> str:
    """Render validated pipeline report dictionaries as one Chinese Markdown report."""

    if not reports:
        raise ValueError("at least one pipeline report is required")

    all_passed = all(
        report.get("status") == "passed" and not _binding_failed(report)
        for report in reports
    )
    total_seconds = sum(
        float(report["total_duration_seconds"])
        for report in reports
        if _is_number(report.get("total_duration_seconds"))
    )
    lines = [
        f"# {_escape_cell(title)}",
        "",
        *_quick_overview_lines(reports),
        "",
        "## 任务概览",
        "",
        "| 项目 | 结果 |",
        "| --- | --- |",
        f"| 试卷数量 | {len(reports)} |",
        f"| 最终状态 | {'全部通过' if all_passed else '存在未通过试卷'} |",
        f"| 各卷墙钟耗时合计 | {_format_duration(total_seconds)} |",
        "",
        "> 计时为墙钟时间，包含工具等待；中断或并行阶段可能互相重叠，因此阶段耗时不应直接相加。",
        "",
    ]

    for index, report in enumerate(reports, start=1):
        label = _safe_label(report.get("label"), index)
        result = report.get("result") if isinstance(report.get("result"), dict) else {}
        lines.extend(
            [
                f"## {index}. {_escape_cell(label)}",
                "",
                "### 最终结果",
                "",
                "| 项目 | 结果 |",
                "| --- | --- |",
                f"| 管线状态 | {_status_label(report.get('status'))} |",
                f"| 总墙钟耗时 | {_format_duration(report.get('total_duration_seconds'))} |",
                f"| 正文页数 | {_display_value(result.get('expected_body_pages'))} |",
                f"| 首页页数 | {_display_value(result.get('front_pages'))} |",
                f"| 印刷赋分合计 | {_display_value(result.get('printed_percent_total'))}% |",
                f"| 派生赋分合计 | {_display_value(result.get('derived_percent_total'))}% |",
                f"| PDF 总页数 | {_display_value(result.get('final_pdf_pages'))} |",
                f"| 预览页数 | {_display_value(result.get('preview_count'))} |",
                f"| 最终顶部差异 | {_format_mm(result.get('top_spread_mm'))} |",
                f"| 最终底部差异（排除尾页） | {_format_mm(result.get('bottom_spread_mm'))} |",
                "",
                *_alignment_failure_lines(report, result),
                "",
                "### 整卷视觉 AI 审计与保守回退",
                "",
                *_ai_layout_audit_lines(result),
                "",
                "### 答题卡配图需求",
                "",
                *_visual_requirement_lines(result),
                "",
                "### 各流程耗时",
                "",
                "| 序号 | 流程 | 执行方 | 状态 | 耗时 |",
                "| ---: | --- | --- | --- | ---: |",
            ]
        )
        stages = report.get("stages")
        if not isinstance(stages, list):
            raise ValueError("pipeline report stages must be a list")
        for stage_index, stage in enumerate(stages, start=1):
            if not isinstance(stage, dict):
                continue
            name = str(stage.get("name") or "未命名步骤")
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(stage_index),
                        _escape_cell(_stage_label(name)),
                        _source_label(stage.get("source")),
                        _status_label(stage.get("status")),
                        _format_duration(stage.get("duration_seconds")),
                    ]
                )
                + " |"
            )

        lines.extend(["", "### 参数调整、失败与重试", ""])
        adjustments = _adjustment_lines(report)
        lines.extend(f"- {line}" for line in adjustments)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _quick_overview_lines(reports: list[dict[str, Any]]) -> list[str]:
    passed_count = sum(
        report.get("status") == "passed" and not _binding_failed(report)
        for report in reports
    )
    failed_reports: list[tuple[int, dict[str, Any]]] = []
    visual_rows: list[
        tuple[str, list[str], list[str], list[str], list[str], str]
    ] = []
    missing_visual_labels: list[str] = []

    for index, report in enumerate(reports, start=1):
        label = _safe_label(report.get("label"), index)
        result = report.get("result") if isinstance(report.get("result"), dict) else {}
        if report.get("status") != "passed" or _binding_failed(report):
            failed_reports.append((index, report))

        preprinted = result.get("preprinted_visual_items")
        uncertain = result.get("uncertain_visual_items")
        if not isinstance(preprinted, list) or not isinstance(uncertain, list):
            missing_visual_labels.append(label)
            continue
        approved_id_set, embedded_id_set, failed_id_set = _binding_item_sets(result)
        cancelled_id_set = _binding_cancelled_ids(result)
        required_ids = _visual_item_ids(preprinted)
        pending_ids = [
            item_id for item_id in required_ids
            if item_id not in approved_id_set and item_id not in cancelled_id_set
        ]
        approved_ids = [
            item_id
            for item_id in required_ids
            if item_id in approved_id_set
            and item_id not in embedded_id_set
            and item_id not in failed_id_set
        ]
        failed_ids = [item_id for item_id in required_ids if item_id in failed_id_set]
        uncertain_ids = _visual_item_ids(uncertain)
        if pending_ids or approved_ids or failed_ids or uncertain_ids:
            visual_rows.append(
                (
                    label,
                    _visual_item_labels(preprinted, pending_ids),
                    _visual_item_labels(preprinted, approved_ids),
                    _visual_item_labels(preprinted, failed_ids),
                    _visual_item_labels(uncertain, uncertain_ids),
                    "配图绑定失败" if _binding_failed(report) else _status_label(report.get("status")),
                )
            )

    explicit_visual_count = sum(bool(row[1] or row[2] or row[3]) for row in visual_rows)
    uncertain_visual_count = sum(bool(row[4]) for row in visual_rows)
    lines = [
        "## 一分钟总览",
        "",
        (
            f"> **共 {len(reports)} 份：正确导出 {passed_count} 份，"
            f"未正确导出 {len(failed_reports)} 份；明确待补图 {explicit_visual_count} 份，"
            f"另有 {uncertain_visual_count} 份需要先确认是否补图。**"
        ),
        "",
        "### 1. 需要补图或待确认的卷子",
        "",
    ]
    if visual_rows:
        lines.extend(
            [
                "| 卷子 | 待审批题号 | 已审批待执行 | 绑定失败 | 待确认题号 | 导出状态 |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for label, pending_ids, approved_ids, failed_ids, uncertain_ids, export_status in visual_rows:
            lines.append(
                f"| {_escape_cell(label)} | {_format_id_summary(pending_ids)} | "
                f"{_format_id_summary(approved_ids)} | {_format_id_summary(failed_ids)} | "
                f"{_format_id_summary(uncertain_ids)} | {export_status} |"
            )
    else:
        lines.append("- 没有已确认的待补图卷子。")
    if missing_visual_labels:
        labels = "、".join(_escape_cell(label) for label in missing_visual_labels)
        lines.append(
            f"> 配图状态无法确认：{labels}。这些卷子的管线报告缺少配图明细。"
        )

    lines.extend(["", "### 2. 未正确导出的卷子", ""])
    if not failed_reports:
        lines.append("- 所有卷子均已正确导出。")
        return lines

    lines.extend(
        [
            "| 卷子 | 大概原因 | 框线最终差异与标准 | 距离标准还差 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for index, report in failed_reports:
        label = _safe_label(report.get("label"), index)
        result = report.get("result") if isinstance(report.get("result"), dict) else {}
        reason, measurement, excess = _quick_failure_summary(report, result)
        lines.append(
            f"| {_escape_cell(label)} | {_escape_cell(reason)} | "
            f"{_escape_cell(measurement)} | {_escape_cell(excess)} |"
        )
    return lines


def _quick_failure_summary(
    report: dict[str, Any],
    result: dict[str, Any],
) -> tuple[str, str, str]:
    binding = result.get("prompt_image_binding")
    if isinstance(binding, dict) and binding.get("status") == "failed":
        code = str(binding.get("failure_code") or "BINDING_FAILED")
        return f"审批后统一配图失败（{code}）", "正式 PDF 未替换", "需修正后整卷重新执行"
    history = result.get("alignment_history")
    entries = [entry for entry in history if isinstance(entry, dict)] if isinstance(history, list) else []
    if entries and entries[-1].get("passed") is not True:
        final_entry = entries[-1]
        top = final_entry.get("top_spread_mm")
        bottom = final_entry.get("bottom_spread_mm")
        tolerance = final_entry.get("tolerance_mm")
        measurement = (
            f"顶部 {_format_mm(top)}；底部 {_format_mm(bottom)}；标准 ≤ {_format_mm(tolerance)}"
        )
        if _is_number(top) and _is_number(bottom) and _is_number(tolerance):
            top_excess = max(0.0, float(top) - float(tolerance))
            bottom_excess = max(0.0, float(bottom) - float(tolerance))
            excess_parts: list[str] = []
            if top_excess > 1e-9:
                excess_parts.append(f"顶部超标 {top_excess:.3f} mm")
            if bottom_excess > 1e-9:
                excess_parts.append(f"底部超标 {bottom_excess:.3f} mm")
            excess = "、".join(excess_parts) or "测量值未超标，但报告判定未通过"
        else:
            excess = "测量明细不完整"
        return "页框未对齐", measurement, excess

    conflicts = result.get("ai_layout_conflicts")
    if isinstance(conflicts, list) and conflicts:
        return "AI 布局与 outline 结构冲突", "—", "—"
    reinspection = result.get("reinspection_required_items")
    if isinstance(reinspection, list) and reinspection:
        return "AI 题型复判尚未完成", "—", "—"
    invalid_fallback = result.get("invalid_fallback_items")
    if isinstance(invalid_fallback, list) and invalid_fallback:
        return "unknown 保守回退字段不合规", "—", "—"

    failed_stage_names = [
        str(stage.get("name") or "未命名步骤")
        for stage in report.get("stages", [])
        if isinstance(stage, dict) and stage.get("status") == "failed"
    ]
    if failed_stage_names:
        reasons = "、".join(_concise_stage_label(name) for name in failed_stage_names)
        return reasons, "—", "—"
    if report.get("status") == "running":
        return "管线仍在运行，尚未形成最终 PDF", "—", "—"
    return "管线未完成，未记录明确失败阶段", "—", "—"


def _visual_item_ids(items: list[object]) -> list[str]:
    ids: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("id") is not None:
            ids.append(str(item["id"]))
        else:
            ids.append("未记录")
    return ids


def _visual_item_labels(items: list[object], item_ids: list[str]) -> list[str]:
    labels: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        machine_id = str(item["id"])
        display_id = str(item.get("display_id") or machine_id)
        labels[machine_id] = display_id
    return [labels.get(item_id, item_id) for item_id in item_ids]


def _format_id_summary(item_ids: list[str]) -> str:
    if not item_ids:
        return "—"
    return _escape_cell("、".join(item_ids))


def _alignment_failure_lines(
    report: dict[str, Any],
    result: dict[str, Any],
) -> list[str]:
    history = result.get("alignment_history")
    if not isinstance(history, list) or not history:
        return []
    entries = [entry for entry in history if isinstance(entry, dict)]
    if not entries:
        return []
    final_entry = entries[-1]
    if report.get("status") != "failed" or final_entry.get("passed") is True:
        return []

    tolerance = final_entry.get("tolerance_mm")
    lines = [
        "### 页框对齐未通过明细",
        "",
        (
            "> 判定标准：每次测量的顶部差异和底部差异必须同时不超过 "
            f"{_format_mm(tolerance)}。`pass 0` 是初始测量，不计入最大校正轮数。"
        ),
        "",
        "| 测量轮次 | 顶部差异 | 底部差异 | 判定标准 | 结果 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for entry in entries:
        pass_number = entry.get("pass")
        label = "初始测量（pass 0）" if pass_number == 0 else f"第 {pass_number} 轮校正"
        passed = entry.get("passed") is True
        lines.append(
            f"| {label} | {_format_mm(entry.get('top_spread_mm'))} | "
            f"{_format_mm(entry.get('bottom_spread_mm'))} | "
            f"≤ {_format_mm(entry.get('tolerance_mm'))} | "
            f"{'通过' if passed else '未通过'} |"
        )

    pass_number = final_entry.get("pass")
    lines.extend(
        [
            "",
            (
                f"> **最终结论：完成 {pass_number} 轮校正后仍未满足 "
                f"{_format_mm(tolerance)} 的页框对齐标准。**"
            ),
        ]
    )
    return lines


def _ai_layout_audit_lines(result: dict[str, Any]) -> list[str]:
    if "ai_layout_conflicts" in result:
        conflicts = result.get("ai_layout_conflicts")
        legacy: list[str] = []
        if isinstance(conflicts, list) and not conflicts:
            legacy.append("- 未检测到 AI 布局与 outline 的结构冲突。")
        elif isinstance(conflicts, list):
            legacy.append(
                f"> **检测到 {len(conflicts)} 项 AI 布局与前期结构文件冲突；本卷不得静默继续构建。**"
            )
            for conflict in conflicts:
                legacy.append(_ai_layout_conflict_row(conflict))
        percent_total = result.get("printed_percent_total")
        if _is_number(percent_total) and int(percent_total) != 100:
            legacy.append(
                f"> **印刷百分比合计为 {int(percent_total)}%，不是 100%；已原样保留并列入异常汇报。**"
            )
        fallback = result.get("fallback_layout_items")
        if isinstance(fallback, list) and fallback:
            ids = "、".join(
                _escape_cell(item.get("id", "未记录"))
                for item in fallback if isinstance(item, dict)
            )
            legacy.append(
                f"> **旧版题号 {ids} 在二次视觉判断后仍为 unknown，已使用 95mm 保守回退。**"
            )
        elif isinstance(fallback, list):
            legacy.append("- 没有题目使用 `unknown` 长框回退。")
        return legacy
    lines = [
        f"- AI 输出状态：{_escape_cell(result.get('ai_paper_status', '未记录'))}。",
        f"- 人工确认轮次：{_display_value(result.get('human_confirmation_rounds'))}。",
        f"- AI revision / attempt：{_display_value(result.get('ai_revision'))} / {_display_value(result.get('ai_attempt'))}。",
        f"- AI 自报实际总分：{_display_value(result.get('actual_total_score'))}。",
        f"- 印刷占比合计：{_display_value(result.get('printed_percent_total'))}%。",
        f"- 派生占比合计：{_display_value(result.get('derived_percent_total'))}%。",
    ]
    fallback_ids = result.get("unknown_fallback_item_ids")
    if isinstance(fallback_ids, list) and fallback_ids:
        lines.append(
            "> **以下机器题块在二次视觉检查后仍使用 unknown/95mm 保守回退："
            + "、".join(_escape_cell(item) for item in fallback_ids)
            + "。**"
        )
    elif isinstance(fallback_ids, list):
        lines.append("- 没有题块使用 `unknown/95mm` 保守回退。")
    else:
        lines.append("> unknown/95mm 回退清单未记录，必须人工复核。")
    return lines


def _ai_layout_conflict_row(conflict: object) -> str:
    if not isinstance(conflict, dict):
        return "| 未记录 | 未记录 | 未记录 | 未记录 |"
    code = str(conflict.get("code") or "未记录")
    labels = {
        "question_id_mismatch": "大题 ID 集合不一致",
        "item_id_mismatch": "小题 ID 集合不一致",
        "score_mismatch": "大题分值不一致",
        "percent_mismatch": "百分比不一致",
        "question_order_mismatch": "大题顺序不一致",
        "item_order_mismatch": "小题顺序不一致",
        "duplicate_question_ids": "大题 ID 重复",
        "duplicate_item_ids": "小题 ID 重复",
    }
    question_id = conflict.get("question_id", "-")
    if code in {"question_id_mismatch", "item_id_mismatch"}:
        expected = "缺失：" + _display_id_list(conflict.get("missing_ids"))
        actual = "多出：" + _display_id_list(conflict.get("extra_ids"))
    elif code in {"question_order_mismatch", "item_order_mismatch"}:
        expected = _display_id_list(conflict.get("outline_ids"))
        actual = _display_id_list(conflict.get("ai_ids"))
    elif code in {"duplicate_question_ids", "duplicate_item_ids"}:
        expected = "不得重复"
        actual = _display_id_list(conflict.get("ids"))
    else:
        expected = _display_value(conflict.get("outline_value"))
        actual = _display_value(conflict.get("ai_value"))
    return (
        f"| {_escape_cell(labels.get(code, code))} | {_escape_cell(question_id)} | "
        f"{_escape_cell(expected)} | {_escape_cell(actual)} |"
    )


def _display_id_list(value: object) -> str:
    if not isinstance(value, list) or not value:
        return "无"
    return "、".join(str(item) for item in value)


def _visual_requirement_lines(result: dict[str, Any]) -> list[str]:
    preprinted = result.get("preprinted_visual_items")
    uncertain = result.get("uncertain_visual_items")
    if not isinstance(preprinted, list) or not isinstance(uncertain, list):
        return [
            "> 配图明细未写入管线报告，必须人工复核；不能据此认定本卷不需要预置图。"
        ]

    display_ids = {
        str(item["id"]): str(item.get("display_id") or item["id"])
        for item in [*preprinted, *uncertain]
        if isinstance(item, dict) and item.get("id") is not None
    }

    lines = [
        f"- 必须预置图的小题：{len(preprinted)} 个。",
        f"- 待视觉复核的小题：{len(uncertain)} 个。",
    ]
    asset_status = result.get("visual_asset_status")
    approved_id_set, embedded_id_set, failed_id_set = _binding_item_sets(result)
    cancelled_id_set = _binding_cancelled_ids(result)
    binding = result.get("prompt_image_binding")
    binding_status = binding.get("status") if isinstance(binding, dict) else None
    if preprinted:
        if binding_status == "failed":
            failure_code = binding.get("failure_code", "BINDING_FAILED")
            status_line = f"- 当前处理状态：审批后统一绑定失败（{_escape_cell(failure_code)}）；正式 PDF 未被替换。"
        elif binding_status == "cancelled":
            status_line = "- 当前处理状态：本卷配图需求已按审批取消；正式 PDF 版式未改写。"
        elif asset_status == "embedded":
            status_line = (
                "- 当前处理状态：用户提供的题面底图已缩放放入对应答题框，带图版本已重新编译。"
            )
        elif approved_id_set:
            status_line = "- 当前处理状态：clean 图片已整卷审批，等待统一绑定执行。"
        else:
            status_line = (
                "- 当前处理状态：无图初版已生成；等待人工在外部目录提供适合答题卡的题面底图，"
                "然后缩放到对应答题框并重新编译。"
            )
        lines.extend(
            [
                status_line,
                "",
                "| 显示题号 | 分类 | 图形类型 | 当前处理 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in preprinted:
            item_id = str(item.get("id")) if isinstance(item, dict) else ""
            if item_id in embedded_id_set:
                handling = "已嵌入并重新编译"
            elif item_id in cancelled_id_set:
                handling = "已审批取消配图"
            elif item_id in failed_id_set:
                handling = "审批后统一绑定失败，正式 PDF 未替换"
            elif item_id in approved_id_set:
                handling = "clean 图片已审批，待整卷统一执行"
            else:
                handling = "待人工补图后缩放并重编译（先生成 clean 图片并整卷审批）"
            lines.append(_visual_item_row(item, handling))
    else:
        lines.append("- 当前处理状态：未发现必须预置题面图的小题。")

    if uncertain:
        lines.extend(
            [
                "",
                "| 待复核题号 | 分类 | 图形类型 | 当前处理 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in uncertain:
            lines.append(_visual_item_row(item, "人工复核后决定是否补图"))
    if isinstance(binding, dict):
        non_default = binding.get("non_default_placements")
        if isinstance(non_default, list) and non_default:
            lines.extend(
                [
                    "",
                    "#### 非默认图片排列审计",
                    "",
                    "| 题号 | 模式 | 重复数 | 间距 |",
                    "| --- | --- | ---: | ---: |",
                ]
            )
            for item in non_default:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"| {_escape_cell(display_ids.get(str(item.get('id')), item.get('id', '未记录')))} | "
                    f"{_escape_cell(item.get('mode', '未记录'))} | "
                    f"{_display_value(item.get('repeat_count'))} | "
                    f"{_format_mm(item.get('gap_mm'))} |"
                )
        overrides = binding.get("height_overrides")
        if isinstance(overrides, list) and overrides:
            lines.extend(
                [
                    "",
                    "#### 框高覆盖审计",
                    "",
                    "| 题号 | 原框高 | 新框高 |",
                    "| --- | ---: | ---: |",
                ]
            )
            for item in overrides:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"| {_escape_cell(display_ids.get(str(item.get('id')), item.get('id', '未记录')))} | "
                    f"{_escape_cell(item.get('from', '未记录'))} | "
                    f"{_escape_cell(item.get('to', '未记录'))} |"
                )
    return lines


def _binding_item_sets(result: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    binding = result.get("prompt_image_binding")
    binding_data = binding if isinstance(binding, dict) else {}
    approved = binding_data.get("approved_visual_item_ids")
    embedded = binding_data.get("embedded_visual_item_ids", result.get("embedded_visual_item_ids"))
    failed = binding_data.get("failed_visual_item_ids")
    embedded_set = {str(item) for item in embedded} if isinstance(embedded, list) else set()
    approved_set = {str(item) for item in approved} if isinstance(approved, list) else set()
    return (
        approved_set | embedded_set,
        embedded_set,
        {str(item) for item in failed} if isinstance(failed, list) else set(),
    )


def _binding_failed(report: dict[str, Any]) -> bool:
    result = report.get("result")
    if not isinstance(result, dict):
        return False
    binding = result.get("prompt_image_binding")
    return isinstance(binding, dict) and binding.get("status") == "failed"


def _binding_cancelled_ids(result: dict[str, Any]) -> set[str]:
    binding = result.get("prompt_image_binding")
    if not isinstance(binding, dict):
        return set()
    cancelled = binding.get("cancelled_visual_item_ids")
    return {str(item) for item in cancelled} if isinstance(cancelled, list) else set()


def _visual_item_row(item: object, handling: str) -> str:
    if not isinstance(item, dict):
        return f"| 未记录 | 未记录 | 未记录 | {handling} |"
    display_id = _escape_cell(item.get("display_id", item.get("id", "未记录")))
    requirement = _VISUAL_REQUIREMENT_LABELS.get(
        str(item.get("visual_requirement")),
        str(item.get("visual_requirement") or "未记录"),
    )
    visual_type = _VISUAL_TYPE_LABELS.get(
        str(item.get("visual_type")),
        str(item.get("visual_type") or "未记录"),
    )
    return (
        f"| {display_id} | {_escape_cell(requirement)} | {_escape_cell(visual_type)} | "
        f"{handling} |"
    )


def _load_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"pipeline report does not exist: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"pipeline report must be an object: {path}")
    if not isinstance(data.get("stages"), list):
        raise ValueError(f"pipeline report stages must be a list: {path}")
    _hydrate_alignment_history(data, path)
    _hydrate_visual_requirements(data, path)
    return data


def _hydrate_alignment_history(report: dict[str, Any], report_path: Path) -> None:
    """Read a sibling frame report for older pipeline reports that lack summaries."""

    result = report.get("result") if isinstance(report.get("result"), dict) else {}
    if isinstance(result.get("alignment_history"), list) and result["alignment_history"]:
        return
    alignment_path = report_path.with_name("frame_alignment.json")
    if not alignment_path.is_file():
        return
    tolerance = _report_alignment_tolerance(report, result)
    if not _is_number(tolerance):
        return
    try:
        history = load_alignment_pass_summaries(
            alignment_path,
            tolerance_mm=float(tolerance),
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return
    result["alignment_history"] = history
    report["result"] = result


def _hydrate_visual_requirements(report: dict[str, Any], report_path: Path) -> None:
    """Fill report visual details even when finalization stopped before copying them."""

    result = report.get("result") if isinstance(report.get("result"), dict) else {}
    if isinstance(result.get("preprinted_visual_items"), list) and isinstance(
        result.get("uncertain_visual_items"), list
    ):
        return
    manifest_path = report_path.with_name("visual_requirements.json")
    if not manifest_path.is_file():
        return
    try:
        manifest = load_visual_requirements(manifest_path)
        details = visual_requirement_report_data(manifest)
    except (OSError, ValueError, json.JSONDecodeError):
        return
    result["preprinted_visual_items"] = details["preprinted_visual_items"]
    result["uncertain_visual_items"] = details["uncertain_visual_items"]
    result.setdefault("visual_asset_status", details["visual_asset_status"])
    report["result"] = result


def _report_alignment_tolerance(
    report: dict[str, Any],
    result: dict[str, Any],
) -> object:
    finalization = (
        report.get("finalization_inputs")
        if isinstance(report.get("finalization_inputs"), dict)
        else {}
    )
    configuration = (
        report.get("configuration")
        if isinstance(report.get("configuration"), dict)
        else {}
    )
    return finalization.get(
        "alignment_tolerance_mm",
        configuration.get(
            "alignment_tolerance_mm",
            result.get("alignment_tolerance_mm", DEFAULT_ALIGNMENT_TOLERANCE_MM),
        ),
    )


def _adjustment_lines(report: dict[str, Any]) -> list[str]:
    result = report.get("result") if isinstance(report.get("result"), dict) else {}
    configuration = (
        report.get("configuration") if isinstance(report.get("configuration"), dict) else {}
    )
    finalization = (
        report.get("finalization_inputs")
        if isinstance(report.get("finalization_inputs"), dict)
        else {}
    )
    actual_tolerance = finalization.get(
        "alignment_tolerance_mm",
        configuration.get("alignment_tolerance_mm", result.get("alignment_tolerance_mm")),
    )
    default_tolerance = finalization.get(
        "default_alignment_tolerance_mm",
        configuration.get(
            "default_alignment_tolerance_mm",
            result.get("default_alignment_tolerance_mm", DEFAULT_ALIGNMENT_TOLERANCE_MM),
        ),
    )
    build_tolerance = configuration.get("alignment_tolerance_mm")
    final_tolerance = finalization.get("alignment_tolerance_mm")
    actual_pass_limit = configuration.get(
        "max_alignment_passes",
        result.get("max_alignment_passes"),
    )
    default_pass_limit = configuration.get(
        "default_max_alignment_passes",
        result.get(
            "default_max_alignment_passes",
            DEFAULT_MAX_ALIGNMENT_PASSES,
        ),
    )

    lines: list[str] = []
    printed_percent_total = result.get("printed_percent_total")
    if _is_number(printed_percent_total) and int(printed_percent_total) != 100:
        lines.append(
            f"印刷赋分合计为 {int(printed_percent_total)}%，与 100% 不一致；报告按原题标题保留，未自动改写。"
        )
    derived_percent_ids = result.get("derived_percent_question_ids")
    if isinstance(derived_percent_ids, list) and derived_percent_ids:
        lines.append(
            "以下大题标题未印百分比，首页赋分按大题分值用最大余数法派生："
            + "、".join(_escape_cell(item_id) for item_id in derived_percent_ids)
            + "。"
        )
    if _is_number(actual_tolerance) and _is_number(default_tolerance):
        if abs(float(actual_tolerance) - float(default_tolerance)) > 1e-9:
            lines.append(
                "页框对齐容差由默认 "
                f"{float(default_tolerance):.3f} mm 调整为 {float(actual_tolerance):.3f} mm。"
            )
        else:
            lines.append(f"页框对齐容差保持默认值 {float(default_tolerance):.3f} mm。")
    else:
        lines.append("页框对齐容差未记录。")

    if _is_number(build_tolerance) and _is_number(final_tolerance):
        if abs(float(build_tolerance) - float(final_tolerance)) > 1e-9:
            lines.append(
                f"构建容差 {float(build_tolerance):.3f} mm 与最终验收容差 "
                f"{float(final_tolerance):.3f} mm 不一致。"
            )

    if isinstance(actual_pass_limit, int) and isinstance(default_pass_limit, int):
        if actual_pass_limit != default_pass_limit:
            lines.append(
                f"最大对齐校正轮数由默认 {default_pass_limit} 调整为 {actual_pass_limit}。"
            )

    alignment_pass = result.get("alignment_pass")
    if isinstance(alignment_pass, int):
        lines.append(f"最终在对齐 pass {alignment_pass} 通过验收。")

    stages = [stage for stage in report.get("stages", []) if isinstance(stage, dict)]
    failed = [stage for stage in stages if stage.get("status") == "failed"]
    retries = [stage for stage in stages if "retry" in str(stage.get("name", "")).lower()]
    if failed:
        details = "；".join(
            f"{_stage_label(str(stage.get('name') or '未命名步骤'))}"
            f"（{_format_duration(stage.get('duration_seconds'))}）"
            for stage in failed
        )
        lines.append(f"检测到失败阶段：{details}。最终状态以本节上方结果为准。")
    if retries:
        details = "、".join(
            _stage_label(str(stage.get("name") or "未命名步骤")) for stage in retries
        )
        lines.append(f"检测到重试阶段：{details}。")
    if not failed and not retries and report.get("status") == "passed":
        lines.append("未检测到失败或重试阶段。")
    return lines


def _stage_label(name: str) -> str:
    label = _STAGE_LABELS.get(name)
    return f"{label}（{name}）" if label else name


def _concise_stage_label(name: str) -> str:
    return _STAGE_LABELS.get(name, name)


def _safe_label(value: object, index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        return f"试卷 {index}"
    label = value.strip().replace("\r", " ").replace("\n", " ")
    if any(term in label for term in _FORBIDDEN_LABEL_TERMS):
        return f"试卷 {index}"
    return label


def _source_label(value: object) -> str:
    return "Agent" if value == "agent" else "脚本"


def _status_label(value: object) -> str:
    return {
        "passed": "通过",
        "failed": "失败",
        "running": "运行中",
    }.get(str(value), "未知")


def _format_duration(value: object) -> str:
    if not _is_number(value):
        return "未记录"
    seconds = max(0.0, float(value))
    if seconds < 60:
        return f"{seconds:.3f} 秒"
    minutes, remaining = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)} 分 {remaining:.3f} 秒"
    hours, remaining_minutes = divmod(minutes, 60)
    return f"{int(hours)} 小时 {int(remaining_minutes)} 分 {remaining:.3f} 秒"


def _format_mm(value: object) -> str:
    return f"{float(value):.3f} mm" if _is_number(value) else "未记录"


def _display_value(value: object) -> str:
    if value is None:
        return "未记录"
    return _escape_cell(str(value))


def _escape_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
