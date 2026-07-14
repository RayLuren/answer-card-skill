from pathlib import Path
import importlib.util
import json
import sys


FULL_PIPELINE_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "full_pipeline.py"
FULL_PIPELINE_SPEC = importlib.util.spec_from_file_location(
    "answercard_full_pipeline_script", FULL_PIPELINE_SCRIPT_PATH
)
assert FULL_PIPELINE_SPEC is not None
full_pipeline_script = importlib.util.module_from_spec(FULL_PIPELINE_SPEC)
assert FULL_PIPELINE_SPEC.loader is not None
sys.modules[FULL_PIPELINE_SPEC.name] = full_pipeline_script
FULL_PIPELINE_SPEC.loader.exec_module(full_pipeline_script)

PipelineError = full_pipeline_script.PipelineError
run_full_pipeline = full_pipeline_script.run_full_pipeline


def _valid_qspec_yaml(*, blocks: str | None = None) -> str:
    inline_blocks = False
    if blocks is None:
        blocks = """
      - id: "1-1"
        kind: "short_answer"
        height: "24mm"
"""
    elif blocks == "[]":
        inline_blocks = True
        blocks = "[]"
    blocks_yaml = f"blocks: {blocks}" if inline_blocks else f"blocks:\n{blocks.rstrip()}"
    return f"""
schema_version: 1
paper:
  title: "Blank Answer Card"
  page_size: "A4"
  omit_front_page: true
  total_score: 10
  margin:
    top: "12mm"
    bottom: "12mm"
    left: "10mm"
    right: "10mm"
style:
  label_width: "13mm"
  border_width: "0.6pt"
  box_gap: "1.5mm"
  title_gap: "2mm"
questions:
  - id: "1"
    title: "Question 1"
    score: 5
    percent: 50
    {blocks_yaml}
  - id: "2"
    title: "Question 2"
    score: 5
    percent: 50
    blocks:
      - id: "2-1"
        kind: "short_answer"
        height: "24mm"
"""


def test_full_pipeline_uses_default_paths_and_prints_summary(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project_root = tmp_path / "project"
    outline_path = project_root / "build" / "outline.json"
    ai_layout_path = project_root / "build" / "ai_layout.json"
    visual_requirements_path = project_root / "build" / "visual_requirements.json"
    qspec_path = project_root / "spec" / "qspec.draft.yaml"
    build_dir = project_root / "build"
    pages_dir = project_root / "build" / "pages"
    pdf_output = build_dir / "answercard.pdf"
    preview_paths = [pages_dir / "page-001.png", pages_dir / "page-002.png"]
    calls = []

    monkeypatch.setattr(full_pipeline_script, "DEFAULT_OUTLINE_PATH", outline_path)
    monkeypatch.setattr(full_pipeline_script, "DEFAULT_AI_LAYOUT_PATH", ai_layout_path)
    monkeypatch.setattr(
        full_pipeline_script,
        "DEFAULT_VISUAL_REQUIREMENTS_PATH",
        visual_requirements_path,
    )
    monkeypatch.setattr(full_pipeline_script, "DEFAULT_QSPEC_PATH", qspec_path)
    monkeypatch.setattr(full_pipeline_script, "DEFAULT_BUILD_DIR", build_dir)
    monkeypatch.setattr(full_pipeline_script, "DEFAULT_PAGES_DIR", pages_dir)

    def fake_extract(pdf_path: Path, output_path: Path) -> Path:
        calls.append(("extract_outline", pdf_path, output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {
                    "source": str(pdf_path),
                    "questions": [
                        {"id": "1", "items": [{"id": "1.1"}, {"id": "1.2"}]},
                        {"id": "2", "items": [{"id": "2.1"}]},
                    ],
                }
            ),
            encoding="utf-8",
        )
        return output_path

    ai_layout_path.parent.mkdir(parents=True, exist_ok=True)
    ai_layout_path.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "id": "1",
                        "score": 5,
                        "percent": 50,
                        "percent_source": "printed",
                        "items": [
                            {
                                "id": item_id,
                                "kind": "short_answer",
                                "height": "24mm",
                                "fallback_after_reinspection": False,
                                "visual_requirement": "no_visual",
                                "visual_type": "none",
                            }
                            for item_id in ("1.1", "1.2")
                        ],
                    },
                    {
                        "id": "2",
                        "score": 5,
                        "percent": 50,
                        "percent_source": "printed",
                        "items": [
                            {
                                "id": "2.1",
                                "kind": "short_answer",
                                "height": "24mm",
                                "fallback_after_reinspection": False,
                                "visual_requirement": "no_visual",
                                "visual_type": "none",
                            }
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_export_visual_requirements(received_ai_layout_path: Path, output_path: Path) -> Path:
        calls.append(("export_visual_requirements", received_ai_layout_path, output_path))
        output_path.write_text('{"schema_version": 1, "questions": []}', encoding="utf-8")
        return output_path

    def fake_ai_layout_to_qspec(
        received_outline_path: Path,
        received_ai_layout_path: Path,
        output_path: Path,
        *,
        paper_title: str,
        omit_front_page: bool,
    ) -> Path:
        calls.append(
            (
                "ai_layout_to_qspec",
                received_outline_path,
                received_ai_layout_path,
                output_path,
                paper_title,
                omit_front_page,
            )
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_valid_qspec_yaml(), encoding="utf-8")
        return output_path

    def fake_build(
        spec_path: Path,
        *,
        build_dir: Path,
        align_pages: bool,
        alignment_tolerance_mm: float,
        max_alignment_passes: int,
    ) -> Path:
        calls.append(
            (
                "build_answer_card",
                spec_path,
                build_dir,
                align_pages,
                alignment_tolerance_mm,
                max_alignment_passes,
            )
        )
        pdf_output.parent.mkdir(parents=True, exist_ok=True)
        pdf_output.write_bytes(b"%PDF-1.7\n")
        return pdf_output

    def fake_render(pdf_path: Path, output_dir: Path, *, dpi: int) -> list[Path]:
        calls.append(("render_pdf_pages", pdf_path, output_dir, dpi))
        output_dir.mkdir(parents=True, exist_ok=True)
        for preview_path in preview_paths:
            preview_path.write_bytes(b"png")
        return preview_paths

    monkeypatch.setattr(full_pipeline_script, "extract_outline", fake_extract)
    monkeypatch.setattr(
        full_pipeline_script,
        "export_visual_requirements",
        fake_export_visual_requirements,
    )
    monkeypatch.setattr(full_pipeline_script, "ai_layout_to_qspec", fake_ai_layout_to_qspec)
    monkeypatch.setattr(full_pipeline_script, "build_answer_card", fake_build)
    monkeypatch.setattr(full_pipeline_script, "render_pdf_pages", fake_render)
    monkeypatch.setattr(
        full_pipeline_script,
        "_inspect_pdf_first_page",
        lambda pdf_path: (2, "blank answer card"),
    )

    exit_code = full_pipeline_script.main(
        [
            str(project_root / "fixtures" / "reference_answer.pdf"),
            "--paper-title",
            "Chemistry Answer Card",
        ]
    )

    assert exit_code == 0
    assert calls == [
        ("extract_outline", project_root / "fixtures" / "reference_answer.pdf", outline_path),
        ("export_visual_requirements", ai_layout_path, visual_requirements_path),
        (
            "ai_layout_to_qspec",
            outline_path,
            ai_layout_path,
            qspec_path,
            "Chemistry Answer Card",
            False,
        ),
        (
            "build_answer_card",
            qspec_path,
            build_dir,
            True,
            full_pipeline_script.DEFAULT_ALIGNMENT_TOLERANCE_MM,
            full_pipeline_script.DEFAULT_MAX_ALIGNMENT_PASSES,
        ),
        ("render_pdf_pages", pdf_output, pages_dir, full_pipeline_script.DEFAULT_DPI),
    ]
    output = capsys.readouterr().out
    assert f"outline: {outline_path}" in output
    assert f"visual_requirements: {visual_requirements_path}" in output
    assert f"qspec: {qspec_path}" in output
    assert f"pdf: {pdf_output}" in output
    assert "question_count: 2" in output
    assert "item_count: 3" in output
    assert "previews: 2" in output
    assert "sanity: passed" in output

    report = json.loads((build_dir / "pipeline_report.json").read_text(encoding="utf-8"))
    assert report["label"] == "Chemistry Answer Card"
    assert report["configuration"]["alignment_tolerance_mm"] == 0.7
    assert report["configuration"]["max_alignment_passes"] == 3


def test_full_pipeline_reports_stage_name_on_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    def fake_extract(pdf_path: Path, output_path: Path) -> Path:
        raise RuntimeError("cannot read structure")

    monkeypatch.setattr(full_pipeline_script, "DEFAULT_OUTLINE_PATH", tmp_path / "build" / "outline.json")
    monkeypatch.setattr(full_pipeline_script, "extract_outline", fake_extract)

    exit_code = full_pipeline_script.main(
        [str(tmp_path / "reference_answer.pdf"), "--paper-title", "Chemistry Answer Card"]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error: extract_outline failed: cannot read structure" in captured.err


def test_full_pipeline_requires_ai_layout(tmp_path: Path, monkeypatch, capsys) -> None:
    outline_path = tmp_path / "build" / "outline.json"
    missing_ai_layout = tmp_path / "build" / "ai_layout.json"

    def fake_extract(pdf_path: Path, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps({"questions": [{"id": "1", "items": [{"id": "1-1"}]}]}),
            encoding="utf-8",
        )
        return output_path

    monkeypatch.setattr(full_pipeline_script, "DEFAULT_OUTLINE_PATH", outline_path)
    monkeypatch.setattr(full_pipeline_script, "DEFAULT_AI_LAYOUT_PATH", missing_ai_layout)
    monkeypatch.setattr(full_pipeline_script, "extract_outline", fake_extract)

    exit_code = full_pipeline_script.main(
        [str(tmp_path / "reference_answer.pdf"), "--paper-title", "Chemistry Answer Card"]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "error: require_ai_layout failed: AI layout is required" in captured.err


def test_full_pipeline_records_outline_conflict_and_percent_total_before_stopping(
    tmp_path: Path,
    monkeypatch,
) -> None:
    outline_path = tmp_path / "build" / "outline.json"
    ai_layout_path = tmp_path / "build" / "ai_layout.json"
    report_path = tmp_path / "build" / "pipeline_report.json"

    def fake_extract(pdf_path: Path, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {
                    "questions": [
                        {"id": "1", "score": 10, "items": [{"id": "1-1"}]}
                    ]
                }
            ),
            encoding="utf-8",
        )
        return output_path

    ai_layout_path.parent.mkdir(parents=True, exist_ok=True)
    ai_layout_path.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "id": "1",
                        "score": 11,
                        "percent": 99,
                        "percent_source": "printed",
                        "items": [
                            {
                                "id": "1-1",
                                "kind": "short_answer",
                                "height": "24mm",
                                "fallback_after_reinspection": False,
                                "visual_requirement": "no_visual",
                                "visual_type": "none",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(full_pipeline_script, "extract_outline", fake_extract)

    try:
        run_full_pipeline(
            tmp_path / "reference.pdf",
            paper_title="Chemistry Answer Card",
            outline_path=outline_path,
            ai_layout_path=ai_layout_path,
            build_dir=tmp_path / "build",
            report_path=report_path,
        )
    except PipelineError as exc:
        assert "score_mismatch" in str(exc)
    else:
        raise AssertionError("outline conflict must stop the pipeline")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["result"]["printed_percent_total"] == 99
    assert report["result"]["ai_layout_conflicts"] == [
        {
            "code": "score_mismatch",
            "question_id": "1",
            "outline_value": 10,
            "ai_value": 11,
        }
    ]


def test_artifact_sanity_passes_with_nonempty_artifacts(tmp_path: Path, monkeypatch) -> None:
    qspec_path = tmp_path / "qspec.yaml"
    pdf_path = tmp_path / "build" / "answercard.pdf"
    preview_path = tmp_path / "build" / "pages" / "page-001.png"
    qspec_path.write_text(_valid_qspec_yaml(), encoding="utf-8")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.7\n")
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_bytes(b"png")

    monkeypatch.setattr(
        full_pipeline_script,
        "_inspect_pdf_first_page",
        lambda received_pdf_path: (1, "blank answer card"),
    )

    summary = full_pipeline_script.PipelineSummary(
        outline_path=tmp_path / "outline.json",
        visual_requirements_path=tmp_path / "visual_requirements.json",
        qspec_path=qspec_path,
        pdf_path=pdf_path,
        preview_dir=preview_path.parent,
        preview_paths=[preview_path],
        question_count=1,
        item_count=1,
    )

    full_pipeline_script.run_artifact_sanity_checks(summary)


def test_artifact_sanity_reports_empty_preview(tmp_path: Path, monkeypatch) -> None:
    qspec_path = tmp_path / "qspec.yaml"
    pdf_path = tmp_path / "build" / "answercard.pdf"
    preview_path = tmp_path / "build" / "pages" / "page-001.png"
    qspec_path.write_text(_valid_qspec_yaml(), encoding="utf-8")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.7\n")
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_bytes(b"")
    monkeypatch.setattr(full_pipeline_script, "_inspect_pdf_first_page", lambda pdf_path: (1, "text"))

    summary = full_pipeline_script.PipelineSummary(
        outline_path=tmp_path / "outline.json",
        visual_requirements_path=tmp_path / "visual_requirements.json",
        qspec_path=qspec_path,
        pdf_path=pdf_path,
        preview_dir=preview_path.parent,
        preview_paths=[preview_path],
        question_count=1,
        item_count=1,
    )

    try:
        full_pipeline_script.run_artifact_sanity_checks(summary)
    except ValueError as exc:
        assert f"preview empty: {preview_path}" in str(exc)
    else:
        raise AssertionError("expected empty preview to fail sanity")


def test_artifact_sanity_reports_overfull_vbox_log(tmp_path: Path, monkeypatch) -> None:
    qspec_path = tmp_path / "qspec.yaml"
    pdf_path = tmp_path / "build" / "answercard.pdf"
    preview_path = tmp_path / "build" / "pages" / "page-001.png"
    log_path = tmp_path / "build" / "answercard.log"
    qspec_path.write_text(_valid_qspec_yaml(), encoding="utf-8")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.7\n")
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_bytes(b"png")
    log_path.write_text("Overfull \\vbox detected", encoding="utf-8")
    monkeypatch.setattr(full_pipeline_script, "_inspect_pdf_first_page", lambda pdf_path: (1, "text"))

    summary = full_pipeline_script.PipelineSummary(
        outline_path=tmp_path / "outline.json",
        visual_requirements_path=tmp_path / "visual_requirements.json",
        qspec_path=qspec_path,
        pdf_path=pdf_path,
        preview_dir=preview_path.parent,
        preview_paths=[preview_path],
        question_count=1,
        item_count=1,
    )

    try:
        full_pipeline_script.run_artifact_sanity_checks(summary)
    except ValueError as exc:
        assert "contains blocked LaTeX log keyword(s): Overfull \\vbox" in str(exc)
    else:
        raise AssertionError("expected Overfull vbox log to fail sanity")
