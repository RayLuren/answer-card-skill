from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from answercard.ai_paper_to_qspec import build_qspec_from_ai_paper
from scripts import full_pipeline
from scripts import finalize_pipeline as finalizer
from test_ai_paper_schema import ready_spec, review_spec


def test_full_pipeline_builds_only_from_ready_ai_paper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ai_path = tmp_path / "ai_paper_spec.json"
    ai_path.write_text(json.dumps(ready_spec(), ensure_ascii=False), encoding="utf-8")
    build_dir = tmp_path / "build"

    def fake_build(spec_path: Path, *, build_dir: Path, **kwargs: object) -> Path:
        destination = Path(build_dir)
        destination.mkdir(parents=True, exist_ok=True)
        pdf = destination / "answercard.pdf"
        pdf.write_bytes(b"pdf")
        return pdf

    def fake_render(pdf_path: Path, pages_dir: Path, *, dpi: int) -> list[Path]:
        destination = Path(pages_dir)
        destination.mkdir(parents=True, exist_ok=True)
        page = destination / "page-001.png"
        page.write_bytes(b"png")
        return [page]

    monkeypatch.setattr(full_pipeline, "build_answer_card", fake_build)
    monkeypatch.setattr(full_pipeline, "render_pdf_pages", fake_render)
    monkeypatch.setattr(full_pipeline, "run_artifact_sanity_checks", lambda summary: None)
    summary = full_pipeline.run_full_pipeline(
        paper_title="试卷",
        ai_paper_path=ai_path,
        source_page_count=2,
        qspec_path=tmp_path / "qspec.yaml",
        visual_requirements_path=tmp_path / "visual_requirements.json",
        build_dir=build_dir,
        pages_dir=build_dir / "pages",
        report_path=build_dir / "pipeline_report.json",
    )
    qspec = yaml.safe_load(summary.qspec_path.read_text(encoding="utf-8"))
    assert qspec["schema_version"] == 2
    assert qspec["questions"][0]["id"] == "q001"
    report = json.loads((build_dir / "pipeline_report.json").read_text(encoding="utf-8"))
    stage_names = [stage["name"] for stage in report["stages"]]
    assert "validate_ai_paper_spec" in stage_names
    assert "ai_paper_to_qspec" in stage_names
    assert all("outline" not in name and "ocr" not in name for name in stage_names)


def test_needs_human_review_cannot_enter_full_pipeline(tmp_path: Path) -> None:
    ai_path = tmp_path / "ai_paper_spec.json"
    ai_path.write_text(json.dumps(review_spec(), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(full_pipeline.PipelineError, match="needs_human_review"):
        full_pipeline.run_full_pipeline(
            paper_title="试卷",
            ai_paper_path=ai_path,
            source_page_count=2,
            build_dir=tmp_path / "build",
            report_path=tmp_path / "build" / "pipeline_report.json",
        )


def test_finalizer_rejects_open_review_and_cleans_explicit_pages(tmp_path: Path) -> None:
    ai_path = tmp_path / "ai_paper_spec.json"
    ai_path.write_text(json.dumps(review_spec(), ensure_ascii=False), encoding="utf-8")
    qspec_path = tmp_path / "qspec.yaml"
    qspec_path.write_text(
        yaml.safe_dump(build_qspec_from_ai_paper(ready_spec(), paper_title="试卷"), allow_unicode=True),
        encoding="utf-8",
    )
    temp_root = tmp_path / ".tmp"
    source_pages = temp_root / "source-pages"
    source_pages.mkdir(parents=True)
    (source_pages / "page-001.png").write_bytes(b"png")
    with pytest.raises(finalizer.FinalizePipelineError, match="human review"):
        finalizer.finalize_pipeline(
            ai_paper_path=ai_path,
            ai_page_count=2,
            qspec_path=qspec_path,
            build_dir=tmp_path / "build",
            report_path=tmp_path / "pipeline_report.json",
            temp_root=temp_root,
            temp_paths=(source_pages,),
        )
    assert not source_pages.exists()
