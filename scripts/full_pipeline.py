from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Callable, TypeVar

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from answercard.ai_paper_schema import READY, ai_paper_audit, load_ai_paper_spec
from answercard.ai_paper_to_qspec import ai_paper_to_qspec
from answercard.frame_alignment import (
    DEFAULT_ALIGNMENT_TOLERANCE_MM,
    DEFAULT_MAX_ALIGNMENT_PASSES,
    load_alignment_pass_summaries,
)
from answercard.pipeline_timing import PipelineTimer
from answercard.schema import load_spec
from answercard.visual_requirements import export_visual_requirements
from build import build_answer_card
from render_pages import DEFAULT_DPI, render_pdf_pages


DEFAULT_AI_PAPER_PATH = PROJECT_ROOT / "build" / "ai_paper_spec.json"
DEFAULT_VISUAL_REQUIREMENTS_PATH = PROJECT_ROOT / "build" / "visual_requirements.json"
DEFAULT_QSPEC_PATH = PROJECT_ROOT / "spec" / "qspec.draft.yaml"
DEFAULT_BUILD_DIR = PROJECT_ROOT / "build"
DEFAULT_PAGES_DIR = PROJECT_ROOT / "build" / "pages"
DEFAULT_PIPELINE_REPORT_PATH = PROJECT_ROOT / "build" / "pipeline_report.json"
T = TypeVar("T")


class PipelineError(RuntimeError):
    """A user-facing deterministic pipeline failure with stage context."""


@dataclass(frozen=True)
class PipelineSummary:
    ai_paper_path: Path
    visual_requirements_path: Path
    qspec_path: Path
    pdf_path: Path
    preview_dir: Path
    preview_paths: list[Path]
    question_count: int
    item_count: int
    sanity_passed: bool = True
    report_path: Path | None = None

    @property
    def preview_count(self) -> int:
        return len(self.preview_paths)


def run_full_pipeline(
    *,
    paper_title: str,
    ai_paper_path: str | Path | None = None,
    source_page_count: int,
    omit_front_page: bool = False,
    visual_requirements_path: str | Path | None = None,
    qspec_path: str | Path | None = None,
    build_dir: str | Path | None = None,
    pages_dir: str | Path | None = None,
    dpi: int = DEFAULT_DPI,
    report_path: str | Path | None = None,
    alignment_tolerance_mm: float = DEFAULT_ALIGNMENT_TOLERANCE_MM,
    max_alignment_passes: int = DEFAULT_MAX_ALIGNMENT_PASSES,
) -> PipelineSummary:
    """Build only from a validated, complete whole-paper visual AI result."""

    resolved_ai = Path(ai_paper_path) if ai_paper_path is not None else DEFAULT_AI_PAPER_PATH
    resolved_build = Path(build_dir) if build_dir is not None else DEFAULT_BUILD_DIR
    resolved_visuals = Path(visual_requirements_path) if visual_requirements_path is not None else (
        resolved_build / "visual_requirements.json" if build_dir is not None else DEFAULT_VISUAL_REQUIREMENTS_PATH
    )
    resolved_qspec = Path(qspec_path) if qspec_path is not None else DEFAULT_QSPEC_PATH
    resolved_pages = Path(pages_dir) if pages_dir is not None else DEFAULT_PAGES_DIR
    resolved_report = Path(report_path) if report_path is not None else (
        resolved_build / "pipeline_report.json" if build_dir is not None else DEFAULT_PIPELINE_REPORT_PATH
    )
    timer = PipelineTimer(resolved_report)
    if timer.data.get("status") != "running":
        timer.begin(label=paper_title, reset=True)
    timer.update_configuration(
        {
            "alignment_tolerance_mm": alignment_tolerance_mm,
            "default_alignment_tolerance_mm": DEFAULT_ALIGNMENT_TOLERANCE_MM,
            "max_alignment_passes": max_alignment_passes,
            "default_max_alignment_passes": DEFAULT_MAX_ALIGNMENT_PASSES,
        }
    )
    ai_paper = _run_stage(
        "validate_ai_paper_spec",
        load_ai_paper_spec,
        resolved_ai,
        page_count=source_page_count,
        timer=timer,
    )
    _run_stage("require_ready_ai_paper", _require_ready, ai_paper, timer=timer)
    timer.update_result(ai_paper_audit(ai_paper))
    written_visuals = _run_stage(
        "export_visual_requirements",
        export_visual_requirements,
        resolved_ai,
        resolved_visuals,
        page_count=source_page_count,
        timer=timer,
    )
    written_qspec = _run_stage(
        "ai_paper_to_qspec",
        ai_paper_to_qspec,
        resolved_ai,
        resolved_qspec,
        page_count=source_page_count,
        paper_title=paper_title,
        omit_front_page=omit_front_page,
        timer=timer,
    )
    try:
        pdf_output = _run_stage(
            "build_answer_card",
            build_answer_card,
            written_qspec,
            build_dir=resolved_build,
            align_pages=True,
            alignment_tolerance_mm=alignment_tolerance_mm,
            max_alignment_passes=max_alignment_passes,
            timer=timer,
        )
    except PipelineError:
        _record_alignment_history(timer, resolved_build / "frame_alignment.json", alignment_tolerance_mm)
        raise
    _record_alignment_history(timer, resolved_build / "frame_alignment.json", alignment_tolerance_mm)
    previews = _run_stage(
        "render_pdf_pages",
        render_pdf_pages,
        pdf_output,
        resolved_pages,
        dpi=dpi,
        timer=timer,
    )
    summary = PipelineSummary(
        ai_paper_path=resolved_ai,
        visual_requirements_path=Path(written_visuals),
        qspec_path=Path(written_qspec),
        pdf_path=Path(pdf_output),
        preview_dir=resolved_pages,
        preview_paths=[Path(path) for path in previews],
        question_count=len(ai_paper["questions"]),
        item_count=sum(len(question["items"]) for question in ai_paper["questions"]),
        report_path=resolved_report,
    )
    _run_stage("artifact_sanity", run_artifact_sanity_checks, summary, timer=timer)
    timer.update_result(
        {
            "question_count": summary.question_count,
            "item_count": summary.item_count,
            "front_pages": 0 if omit_front_page else 1,
            "final_pdf_pages": summary.preview_count,
        }
    )
    return summary


def _run_stage(
    stage: str,
    func: Callable[..., T],
    *args: object,
    timer: PipelineTimer | None = None,
    **kwargs: object,
) -> T:
    try:
        return timer.run(stage, func, *args, **kwargs) if timer is not None else func(*args, **kwargs)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PipelineError(f"{stage} failed: {exc}") from exc


def _require_ready(data: dict[str, object]) -> None:
    if data.get("status") != READY:
        raise ValueError("needs_human_review cannot enter qspec or PDF build")


def _record_alignment_history(timer: PipelineTimer, report_path: Path, tolerance_mm: float) -> None:
    if not report_path.is_file():
        return
    try:
        history = load_alignment_pass_summaries(report_path, tolerance_mm=tolerance_mm)
    except (OSError, ValueError, json.JSONDecodeError):
        return
    timer.update_result({"alignment_history": history})


def run_artifact_sanity_checks(summary: PipelineSummary) -> None:
    failures: list[str] = []
    if not summary.preview_paths:
        failures.append("preview_paths is empty")
    for path in summary.preview_paths:
        if not path.exists() or path.stat().st_size <= 0:
            failures.append(f"preview missing or empty: {path}")
    log_path = summary.pdf_path.parent / "answercard.log"
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        found = [term for term in ("Overfull \\vbox", "Fatal error", "Emergency stop") if term in log_text]
        if found:
            failures.append(f"{log_path} contains blocked keyword(s): {', '.join(found)}")
    spec = load_spec(summary.qspec_path)
    if any(question.score > 0 and not question.blocks for question in spec.questions):
        failures.append("scored question has no answer block")
    if not summary.pdf_path.exists() or summary.pdf_path.stat().st_size <= 0:
        failures.append(f"PDF missing or empty: {summary.pdf_path}")
    if failures:
        raise ValueError("; ".join(failures))


def format_summary(summary: PipelineSummary) -> str:
    lines = [
        "summary:",
        f"  ai_paper_spec: {summary.ai_paper_path}",
        f"  visual_requirements: {summary.visual_requirements_path}",
        f"  qspec: {summary.qspec_path}",
        f"  pdf: {summary.pdf_path}",
        f"  previews: {summary.preview_count}",
        f"  preview_dir: {summary.preview_dir}",
        f"  question_count: {summary.question_count}",
        f"  item_count: {summary.item_count}",
        f"  sanity: {'passed' if summary.sanity_passed else 'failed'}",
    ]
    if summary.report_path is not None:
        lines.append(f"  timing_report: {summary.report_path}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build from a ready whole-paper visual AI result.")
    parser.add_argument("ai_paper_path", type=Path)
    parser.add_argument("--source-page-count", type=int, required=True)
    parser.add_argument("--paper-title", required=True)
    parser.add_argument("--omit-front-page", action="store_true")
    parser.add_argument("--visual-requirements-path", type=Path, default=None)
    parser.add_argument("--qspec-path", type=Path, default=None)
    parser.add_argument("--build-dir", type=Path, default=None)
    parser.add_argument("--pages-dir", type=Path, default=None)
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--alignment-tolerance-mm", type=float, default=DEFAULT_ALIGNMENT_TOLERANCE_MM)
    parser.add_argument("--max-alignment-passes", type=int, default=DEFAULT_MAX_ALIGNMENT_PASSES)
    args = parser.parse_args(argv)
    try:
        summary = run_full_pipeline(
            paper_title=args.paper_title,
            ai_paper_path=args.ai_paper_path,
            source_page_count=args.source_page_count,
            omit_front_page=args.omit_front_page,
            visual_requirements_path=args.visual_requirements_path,
            qspec_path=args.qspec_path,
            build_dir=args.build_dir,
            pages_dir=args.pages_dir,
            dpi=args.dpi,
            report_path=args.report,
            alignment_tolerance_mm=args.alignment_tolerance_mm,
            max_alignment_passes=args.max_alignment_passes,
        )
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
