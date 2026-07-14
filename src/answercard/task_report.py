"""Create one user-facing Markdown report for one answer-card task."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from answercard.frame_alignment import (
    DEFAULT_ALIGNMENT_TOLERANCE_MM,
    DEFAULT_MAX_ALIGNMENT_PASSES,
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
    "ai_layout_judgment": "AI 版面判断",
    "ai_layout_validation": "AI 布局校验",
    "extract_outline": "提取无答案结构",
    "read_outline_summary": "读取结构摘要",
    "require_ai_layout": "检查 AI 布局文件",
    "audit_ai_layout_handoff": "审计 AI 布局与 outline",
    "reject_ai_layout_conflicts": "阻止结构冲突继续构建",
    "validate_ai_layout": "校验 AI 布局结构",
    "prepare_ai_layout_skeleton": "生成无猜测 AI 布局骨架",
    "ai_layout_to_qspec": "生成并校验 qspec",
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

    all_passed = all(report.get("status") == "passed" for report in reports)
    total_seconds = sum(
        float(report["total_duration_seconds"])
        for report in reports
        if _is_number(report.get("total_duration_seconds"))
    )
    lines = [
        f"# {_escape_cell(title)}",
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
                f"| PDF 总页数 | {_display_value(result.get('final_pdf_pages'))} |",
                f"| 预览页数 | {_display_value(result.get('preview_count'))} |",
                f"| 最终顶部差异 | {_format_mm(result.get('top_spread_mm'))} |",
                f"| 最终底部差异（排除尾页） | {_format_mm(result.get('bottom_spread_mm'))} |",
                "",
                "### AI 布局结构复核与保守回退",
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


def _ai_layout_audit_lines(result: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    conflicts = result.get("ai_layout_conflicts")
    if not isinstance(conflicts, list):
        lines.append(
            "> AI 布局与 outline 的结构冲突明细未写入管线报告，必须人工复核。"
        )
    elif not conflicts:
        lines.append("- 未检测到 AI 布局与 outline 的结构冲突。")
    else:
        lines.extend(
            [
                f"> **检测到 {len(conflicts)} 项 AI 布局与前期结构文件冲突；本卷不得静默继续构建。**",
                "",
                "| 冲突类型 | 大题 | outline/期望值 | AI/实际值 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for conflict in conflicts:
            lines.append(_ai_layout_conflict_row(conflict))

    percent_total = result.get("printed_percent_total")
    if _is_number(percent_total):
        if int(percent_total) == 100:
            lines.append("- 印刷百分比合计为 100%。")
        else:
            lines.append(
                f"> **印刷百分比合计为 {int(percent_total)}%，不是 100%；已原样保留并列入异常汇报。**"
            )
    else:
        lines.append("> 印刷百分比合计无法确定，必须人工复核。")

    fallback_items = result.get("fallback_layout_items")
    reinspection_items = result.get("reinspection_required_items")
    invalid_fallback_items = result.get("invalid_fallback_items")
    if isinstance(reinspection_items, list) and reinspection_items:
        item_ids = "、".join(
            _escape_cell(item.get("id", "未记录"))
            for item in reinspection_items
            if isinstance(item, dict)
        )
        lines.append(
            f"> **以下题号首次判断仍为 unknown，尚未完成规定的第二次视觉判断：{item_ids or '未记录'}。该卷不得继续构建。**"
        )
    elif not isinstance(reinspection_items, list):
        lines.append("> 首次 unknown 的复判状态未写入管线报告，必须人工复核。")
    if isinstance(invalid_fallback_items, list) and invalid_fallback_items:
        details = "、".join(
            f"{_escape_cell(item.get('id', '未记录'))}（{_escape_cell(item.get('height', '未记录'))}）"
            for item in invalid_fallback_items
            if isinstance(item, dict)
        )
        lines.append(
            f"> **以下 unknown 项虽标记已复判，但未使用规定的 95mm 保守高度：{details or '未记录'}。该卷不得继续构建。**"
        )
    elif not isinstance(invalid_fallback_items, list):
        lines.append("> unknown 回退字段合法性明细未写入管线报告，必须人工复核。")
    if not isinstance(fallback_items, list):
        lines.append("> 题型复判回退明细未写入管线报告，必须人工复核。")
    elif not fallback_items:
        lines.append("- 没有题目使用 `unknown` 长框回退。")
    else:
        lines.extend(
            [
                f"> **有 {len(fallback_items)} 个题框在第二次视觉判断后仍无法确定题型，已使用保守长框；交付前必须重点检查。**",
                "",
                "| 题号 | 保守留框高度 | 状态 |",
                "| --- | ---: | --- |",
            ]
        )
        for item in fallback_items:
            item_id = item.get("id", "未记录") if isinstance(item, dict) else "未记录"
            height = item.get("height", "未记录") if isinstance(item, dict) else "未记录"
            lines.append(
                f"| {_escape_cell(item_id)} | {_escape_cell(height)} | 二次视觉判断后仍为 unknown |"
            )
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

    lines = [
        f"- 必须预置图的小题：{len(preprinted)} 个。",
        f"- 待视觉复核的小题：{len(uncertain)} 个。",
    ]
    asset_status = result.get("visual_asset_status")
    embedded_ids = result.get("embedded_visual_item_ids")
    embedded_id_set = (
        {str(item_id) for item_id in embedded_ids}
        if isinstance(embedded_ids, list)
        else set()
    )
    if preprinted:
        if asset_status == "embedded":
            status_line = (
                "- 当前处理状态：用户提供的题面底图已缩放放入对应答题框，带图版本已重新编译。"
            )
        else:
            status_line = (
                "- 当前处理状态：无图初版已生成；等待人工在外部目录提供适合答题卡的题面底图，"
                "然后缩放到对应答题框并重新编译。"
            )
        lines.extend(
            [
                status_line,
                "",
                "| 题号 | 分类 | 图形类型 | 当前处理 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in preprinted:
            item_id = str(item.get("id")) if isinstance(item, dict) else ""
            handling = (
                "已嵌入并重新编译"
                if asset_status == "embedded" and item_id in embedded_id_set
                else "待人工补图后缩放并重编译"
            )
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
    return lines


def _visual_item_row(item: object, handling: str) -> str:
    if not isinstance(item, dict):
        return f"| 未记录 | 未记录 | 未记录 | {handling} |"
    item_id = _escape_cell(item.get("id", "未记录"))
    requirement = _VISUAL_REQUIREMENT_LABELS.get(
        str(item.get("visual_requirement")),
        str(item.get("visual_requirement") or "未记录"),
    )
    visual_type = _VISUAL_TYPE_LABELS.get(
        str(item.get("visual_type")),
        str(item.get("visual_type") or "未记录"),
    )
    return (
        f"| {item_id} | {_escape_cell(requirement)} | {_escape_cell(visual_type)} | "
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
    return data


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
