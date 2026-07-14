from __future__ import annotations

import json
from pathlib import Path

from answercard.task_report import write_task_report


def _write_report(
    path: Path,
    *,
    label: str,
    tolerance: float,
    failed_then_retried: bool = False,
) -> Path:
    stages = [
        {
            "id": "001",
            "name": "ai_layout_judgment",
            "source": "agent",
            "status": "passed",
            "duration_seconds": 120.25,
        },
        {
            "id": "002",
            "name": "build_answer_card",
            "source": "script",
            "status": "failed" if failed_then_retried else "passed",
            "duration_seconds": 30.5,
        },
    ]
    if failed_then_retried:
        stages.append(
            {
                "id": "003",
                "name": "build_alignment_retry",
                "source": "script",
                "status": "passed",
                "duration_seconds": 20.0,
            }
        )
    report = {
        "schema_version": 1,
        "status": "passed",
        "label": label,
        "total_duration_seconds": 180.75,
        "stages": stages,
        "finalization_inputs": {
            "alignment_tolerance_mm": tolerance,
            "default_alignment_tolerance_mm": 0.7,
        },
        "configuration": {
            "alignment_tolerance_mm": tolerance,
            "default_alignment_tolerance_mm": 0.7,
            "max_alignment_passes": 3,
            "default_max_alignment_passes": 3,
        },
        "result": {
            "expected_body_pages": 4,
            "front_pages": 1,
            "final_pdf_pages": 5,
            "preview_count": 5,
            "alignment_pass": 2,
            "top_spread_mm": 0.3,
            "bottom_spread_mm": 0.9,
            "printed_percent_total": 100,
            "printed_percent_total_is_100": True,
            "ai_layout_conflicts": [],
            "fallback_layout_items": [],
            "reinspection_required_items": [],
            "invalid_fallback_items": [],
            "visual_asset_status": "awaiting_manual_assets",
            "preprinted_visual_items": [
                {
                    "id": "7-3-1",
                    "visual_requirement": "complete_existing_visual",
                    "visual_type": "chemical_structure",
                }
            ],
            "uncertain_visual_items": [],
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


def test_task_report_records_all_stages_and_tolerance_change(tmp_path: Path) -> None:
    source = _write_report(
        tmp_path / "paper01" / "pipeline_report.json",
        label="模拟试题 01 答题卡",
        tolerance=1.1,
        failed_then_retried=True,
    )
    output = write_task_report([source], tmp_path / "task-report.md")

    text = output.read_text(encoding="utf-8")
    assert "# 答题卡生成任务汇报" in text
    assert "模拟试题 01 答题卡" in text
    assert "AI 版面判断（ai_layout_judgment）" in text
    assert "2 分 0.250 秒" in text
    assert "0.700 mm 调整为 1.100 mm" in text
    assert "检测到失败阶段" in text
    assert "检测到重试阶段" in text
    assert "最终底部差异（排除尾页）" in text
    assert "### 答题卡配图需求" in text
    assert "必须预置图的小题：1 个" in text
    assert "7-3-1" in text
    assert "补全既有图形" in text
    assert "无图初版已生成" in text
    assert "待人工补图后缩放并重编译" in text
    assert "未检测到 AI 布局与 outline 的结构冲突" in text
    assert "没有题目使用 `unknown` 长框回退" in text


def test_task_report_emphasizes_conflicts_non_100_total_and_unknown_fallback(
    tmp_path: Path,
) -> None:
    source = _write_report(
        tmp_path / "pipeline_report.json",
        label="异常试卷",
        tolerance=0.7,
    )
    data = json.loads(source.read_text(encoding="utf-8"))
    data["result"].update(
        {
            "printed_percent_total": 99,
            "printed_percent_total_is_100": False,
            "ai_layout_conflicts": [
                {
                    "code": "item_id_mismatch",
                    "question_id": "2",
                    "missing_ids": ["2"],
                    "extra_ids": ["2-1"],
                }
            ],
            "fallback_layout_items": [{"id": "10-2", "height": "95mm"}],
        }
    )
    source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    output = write_task_report([source], tmp_path / "task-report.md")
    text = output.read_text(encoding="utf-8")

    assert "AI 布局与前期结构文件冲突" in text
    assert "小题 ID 集合不一致" in text
    assert "印刷百分比合计为 99%，不是 100%" in text
    assert "10-2" in text
    assert "二次视觉判断后仍为 unknown" in text


def test_task_report_aggregates_multiple_pdfs_into_one_markdown(tmp_path: Path) -> None:
    first = _write_report(
        tmp_path / "paper01" / "pipeline_report.json",
        label="试卷一答题卡",
        tolerance=0.7,
    )
    second = _write_report(
        tmp_path / "paper02" / "pipeline_report.json",
        label="试卷二答题卡",
        tolerance=0.7,
    )
    output = tmp_path / "batch-report.md"

    written = write_task_report([first, second], output)

    assert written == output
    assert list(tmp_path.glob("*.md")) == [output]
    text = output.read_text(encoding="utf-8")
    assert "| 试卷数量 | 2 |" in text
    assert "## 1. 试卷一答题卡" in text
    assert "## 2. 试卷二答题卡" in text
    assert text.count("# 答题卡生成任务汇报") == 1


def test_task_report_does_not_repeat_reference_answer_label(tmp_path: Path) -> None:
    source = _write_report(
        tmp_path / "pipeline_report.json",
        label="某试卷参考答案",
        tolerance=0.7,
    )

    output = write_task_report([source], tmp_path / "task-report.md")
    text = output.read_text(encoding="utf-8")

    assert "参考答案" not in text
    assert "## 1. 试卷 1" in text


def test_task_report_warns_when_visual_details_are_missing(tmp_path: Path) -> None:
    source = _write_report(
        tmp_path / "pipeline_report.json",
        label="旧格式试卷",
        tolerance=0.7,
    )
    data = json.loads(source.read_text(encoding="utf-8"))
    data["result"].pop("preprinted_visual_items")
    data["result"].pop("uncertain_visual_items")
    source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    output = write_task_report([source], tmp_path / "task-report.md")
    text = output.read_text(encoding="utf-8")

    assert "配图明细未写入管线报告" in text
    assert "不能据此认定本卷不需要预置图" in text


def test_task_report_marks_user_supplied_visual_as_embedded(tmp_path: Path) -> None:
    source = _write_report(
        tmp_path / "pipeline_report.json",
        label="带图试卷",
        tolerance=0.7,
    )
    data = json.loads(source.read_text(encoding="utf-8"))
    data["result"]["visual_asset_status"] = "embedded"
    data["result"]["embedded_visual_item_ids"] = ["7-3-1"]
    source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    output = write_task_report([source], tmp_path / "task-report.md")
    text = output.read_text(encoding="utf-8")

    assert "题面底图已缩放放入对应答题框" in text
    assert "| 7-3-1 | 补全既有图形 | 化学结构 | 已嵌入并重新编译 |" in text
