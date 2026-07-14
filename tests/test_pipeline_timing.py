from __future__ import annotations

import json
from pathlib import Path

from answercard.pipeline_timing import PipelineTimer


def test_pipeline_timer_persists_agent_and_script_stages(tmp_path: Path) -> None:
    report_path = tmp_path / "pipeline_report.json"
    timer = PipelineTimer(report_path)
    timer.begin(label="paper-01")

    timer.start_stage("ai_layout_judgment", source="agent")
    timer.stop_stage("ai_layout_judgment", status="passed")
    result = timer.run("validate_qspec", lambda: 42)
    timer.update_configuration({"alignment_tolerance_mm": 0.7})
    timer.update_result({"final_pdf_pages": 8})
    timer.finish(status="passed")

    assert result == 42
    stored = json.loads(report_path.read_text(encoding="utf-8"))
    assert stored["schema_version"] == 1
    assert stored["status"] == "passed"
    assert stored["label"] == "paper-01"
    assert stored["stages"][0]["source"] == "agent"
    assert stored["stages"][1]["source"] == "script"
    assert stored["stages"][0]["duration_seconds"] >= 0
    assert stored["total_duration_seconds"] >= 0
    assert "_started_epoch_seconds" not in stored
    assert stored["result"]["final_pdf_pages"] == 8
    assert stored["configuration"]["alignment_tolerance_mm"] == 0.7
    assert "ai_layout_judgment" in timer.summary_text()


def test_pipeline_timer_marks_failed_stage_and_pipeline(tmp_path: Path) -> None:
    timer = PipelineTimer(tmp_path / "pipeline_report.json")

    try:
        timer.run("compile_pdf", lambda: (_ for _ in ()).throw(RuntimeError("compile failed")))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected timed stage to fail")

    assert timer.data["status"] == "failed"
    assert timer.data["stages"][-1]["status"] == "failed"
    assert timer.data["total_duration_seconds"] >= 0


def test_pipeline_timer_migrates_existing_finalizer_report(tmp_path: Path) -> None:
    report_path = tmp_path / "pipeline_report.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "started_at": "2026-07-13T00:00:00+00:00",
                "stages": [
                    {
                        "name": "validate_pdf",
                        "status": "passed",
                        "duration_seconds": 0.1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    timer = PipelineTimer(report_path)

    assert timer.data["schema_version"] == 1
    assert timer.data["stages"][0]["id"] == "001"
    assert timer.data["stages"][0]["source"] == "script"
