from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

from pypdf import PdfWriter


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "finalize_pipeline.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("answercard_finalize_pipeline_script", SCRIPT_PATH)
assert SCRIPT_SPEC is not None
finalize_script = importlib.util.module_from_spec(SCRIPT_SPEC)
assert SCRIPT_SPEC.loader is not None
sys.modules[SCRIPT_SPEC.name] = finalize_script
SCRIPT_SPEC.loader.exec_module(finalize_script)


def _write_qspec(path: Path) -> Path:
    path.write_text(
        """
schema_version: 1
paper:
  title: Blank Answer Card
  page_size: A4
  omit_front_page: true
  total_score: 20
  margin: {top: 12mm, bottom: 12mm, left: 10mm, right: 10mm}
style: {label_width: 13mm, border_width: 0.6pt, box_gap: 1.5mm, title_gap: 2mm}
questions:
  - id: "1"
    title: Question 1
    score: 10
    percent: 50
    blocks: [{id: "1-1", kind: short_answer, height: 24mm}]
  - id: "2"
    title: Question 2
    score: 10
    percent: 50
    blocks: [{id: "2-1", kind: short_answer, height: 24mm}]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_pdf(path: Path, pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595.28, height=841.89)
    with path.open("wb") as output_file:
        writer.write(output_file)
    return path


def _prepare_artifacts(tmp_path: Path, *, log_text: str = "compile completed") -> dict[str, Path]:
    project = tmp_path / "project"
    build = project / "build"
    pages = build / "pages"
    temp_root = project / ".tmp"
    evidence = temp_root / "source-pages"
    build.mkdir(parents=True)
    pages.mkdir()
    evidence.mkdir(parents=True)

    qspec = _write_qspec(project / "qspec.yaml")
    tex = build / "answercard.tex"
    tex.write_text(
        "% generated answer card\n"
        "\\pagestyle{answercard}\n"
        "\\def\\@oddfoot{\\hfil{\\QuestionTitleFont\\thepage}\\hfil}%\n",
        encoding="utf-8",
    )
    pdf = _write_pdf(build / "answercard.pdf", 2)
    for page in range(1, 3):
        (pages / f"page-{page:03d}.png").write_bytes(b"png")
    alignment = build / "frame_alignment.json"
    alignment.write_text(
        json.dumps(
            {
                "passes": [
                    {
                        "pass": 1,
                        "top_spread_mm": 0.1,
                        "bottom_spread_mm": 0.2,
                        "pages": [{"page": 1}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    visual_requirements = build / "visual_requirements.json"
    visual_requirements.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "questions": [
                    {
                        "id": "1",
                        "items": [
                            {
                                "id": "1-1",
                                "visual_requirement": "no_visual",
                                "visual_type": "none",
                                "requires_preprinted_visual": False,
                            }
                        ],
                    },
                    {
                        "id": "2",
                        "items": [
                            {
                                "id": "2-1",
                                "visual_requirement": "draw_on_scaffold",
                                "visual_type": "coordinate_system",
                                "requires_preprinted_visual": True,
                            }
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    log = build / "answercard.log"
    log.write_text(log_text, encoding="utf-8")
    (build / "answercard.aux").write_text("aux", encoding="utf-8")
    (build / "outline.json").write_text("{}", encoding="utf-8")
    (evidence / "page-001.png").write_bytes(b"source")
    return {
        "project": project,
        "build": build,
        "pages": pages,
        "temp_root": temp_root,
        "evidence": evidence,
        "qspec": qspec,
        "tex": tex,
        "pdf": pdf,
        "alignment": alignment,
        "visual_requirements": visual_requirements,
        "log": log,
        "report": build / "pipeline_report.json",
    }


def test_finalize_pipeline_validates_cleans_and_retains_audit_artifacts_by_default(
    tmp_path: Path,
) -> None:
    paths = _prepare_artifacts(tmp_path)

    report = finalize_script.finalize_pipeline(
        qspec_path=paths["qspec"],
        pdf_path=paths["pdf"],
        pages_dir=paths["pages"],
        build_dir=paths["build"],
        alignment_report_path=paths["alignment"],
        visual_requirements_path=paths["visual_requirements"],
        report_path=paths["report"],
        log_paths=(paths["log"],),
        front_pages=1,
        temp_paths=(paths["evidence"],),
        temp_root=paths["temp_root"],
    )

    assert report["status"] == "passed"
    assert report["result"]["final_pdf_pages"] == 2
    assert not paths["evidence"].exists()
    assert {path.name for path in paths["build"].iterdir()} == {
        "answercard.tex",
        "answercard.pdf",
        "answercard.aux",
        "answercard.log",
        "frame_alignment.json",
        "visual_requirements.json",
        "outline.json",
        "pages",
        "pipeline_report.json",
    }
    retained_tex = paths["tex"].read_text(encoding="utf-8")
    assert r"\pagestyle{answercard}" in retained_tex
    assert r"\QuestionTitleFont\thepage" in retained_tex
    stored_report = json.loads(paths["report"].read_text(encoding="utf-8"))
    assert stored_report["finalization_inputs"]["alignment_tolerance_mm"] == 0.7
    assert stored_report["result"]["default_alignment_tolerance_mm"] == 0.7
    assert stored_report["result"]["visual_requirement_counts"]["draw_on_scaffold"] == 1
    assert stored_report["result"]["visual_asset_status"] == "awaiting_manual_assets"
    assert stored_report["result"]["preprinted_visual_items"] == [
        {
            "id": "2-1",
            "visual_requirement": "draw_on_scaffold",
            "visual_type": "coordinate_system",
        }
    ]
    assert stored_report["result"]["uncertain_visual_items"] == []
    assert stored_report["result"]["build_artifacts_pruned"] is False
    assert all(stage["name"] != "prune_build_artifacts" for stage in stored_report["stages"])
    assert not list(paths["temp_root"].glob("answercard-final-check-*"))


def test_finalize_pipeline_can_prune_after_success_when_explicitly_requested(
    tmp_path: Path,
) -> None:
    paths = _prepare_artifacts(tmp_path)

    finalize_script.finalize_pipeline(
        qspec_path=paths["qspec"],
        pdf_path=paths["pdf"],
        pages_dir=paths["pages"],
        build_dir=paths["build"],
        alignment_report_path=paths["alignment"],
        visual_requirements_path=paths["visual_requirements"],
        report_path=paths["report"],
        log_paths=(paths["log"],),
        front_pages=1,
        temp_paths=(paths["evidence"],),
        temp_root=paths["temp_root"],
        prune_on_success=True,
    )

    assert {path.name for path in paths["build"].iterdir()} == {
        "answercard.tex",
        "answercard.pdf",
        "frame_alignment.json",
        "visual_requirements.json",
        "pages",
        "pipeline_report.json",
    }
    stored_report = json.loads(paths["report"].read_text(encoding="utf-8"))
    assert stored_report["result"]["build_artifacts_pruned"] is True
    assert stored_report["stages"][-1]["name"] == "prune_build_artifacts"
    assert stored_report["stages"][-1]["status"] == "passed"


def test_finalize_pipeline_failure_still_cleans_temp_and_keeps_diagnostics(tmp_path: Path) -> None:
    paths = _prepare_artifacts(tmp_path, log_text="Fatal error")

    try:
        finalize_script.finalize_pipeline(
            qspec_path=paths["qspec"],
            pdf_path=paths["pdf"],
            pages_dir=paths["pages"],
            build_dir=paths["build"],
            alignment_report_path=paths["alignment"],
            visual_requirements_path=paths["visual_requirements"],
            report_path=paths["report"],
            log_paths=(paths["log"],),
            front_pages=1,
            temp_paths=(paths["evidence"],),
            temp_root=paths["temp_root"],
        )
    except finalize_script.FinalizePipelineError as exc:
        assert "compilation log contains blocked error" in str(exc)
    else:
        raise AssertionError("expected compilation-log validation to fail")

    assert not paths["evidence"].exists()
    assert paths["log"].exists()
    assert (paths["build"] / "answercard.aux").exists()
    stored_report = json.loads(paths["report"].read_text(encoding="utf-8"))
    assert stored_report["status"] == "failed"
    cleanup_stages = [
        stage for stage in stored_report["stages"] if stage["name"] == "cleanup_temporary_artifacts"
    ]
    assert len(cleanup_stages) == 1
    assert cleanup_stages[0]["status"] == "passed"
    assert cleanup_stages[0]["removed_paths"] == [str(paths["evidence"])]


def test_finalize_pipeline_rejects_missing_page_number_rule(tmp_path: Path) -> None:
    paths = _prepare_artifacts(tmp_path)
    paths["tex"].write_text("% page number rule removed\n", encoding="utf-8")

    try:
        finalize_script.finalize_pipeline(
            qspec_path=paths["qspec"],
            pdf_path=paths["pdf"],
            pages_dir=paths["pages"],
            build_dir=paths["build"],
            alignment_report_path=paths["alignment"],
            visual_requirements_path=paths["visual_requirements"],
            report_path=paths["report"],
            log_paths=(paths["log"],),
            front_pages=1,
            temp_root=paths["temp_root"],
        )
    except finalize_script.FinalizePipelineError as exc:
        assert "required centered page-number rule" in str(exc)
    else:
        raise AssertionError("expected missing page-number rule validation to fail")


def test_finalize_pipeline_rejects_preview_count_mismatch(tmp_path: Path) -> None:
    paths = _prepare_artifacts(tmp_path)
    (paths["pages"] / "page-002.png").unlink()

    try:
        finalize_script.finalize_pipeline(
            qspec_path=paths["qspec"],
            pdf_path=paths["pdf"],
            pages_dir=paths["pages"],
            build_dir=paths["build"],
            alignment_report_path=paths["alignment"],
            visual_requirements_path=paths["visual_requirements"],
            report_path=paths["report"],
            log_paths=(paths["log"],),
            front_pages=1,
            temp_root=paths["temp_root"],
        )
    except finalize_script.FinalizePipelineError as exc:
        assert "preview files must be exactly" in str(exc)
    else:
        raise AssertionError("expected preview-count validation to fail")
