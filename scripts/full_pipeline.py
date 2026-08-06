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

from answercard.extract_outline import extract_outline
from answercard.ai_layout_audit import audit_ai_layout_handoff
from answercard.ai_layout_schema import load_ai_layout
from answercard.ai_layout_to_qspec import ai_layout_to_qspec
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


DEFAULT_OUTLINE_PATH = PROJECT_ROOT / "build" / "outline.json"
DEFAULT_AI_LAYOUT_PATH = PROJECT_ROOT / "build" / "ai_layout.json"
DEFAULT_AI_LAYOUT_PROMPT_PATH = PROJECT_ROOT / "prompts" / "ai_layout_judge.md"
DEFAULT_VISUAL_REQUIREMENTS_PATH = PROJECT_ROOT / "build" / "visual_requirements.json"
DEFAULT_QSPEC_PATH = PROJECT_ROOT / "spec" / "qspec.draft.yaml"
DEFAULT_BUILD_DIR = PROJECT_ROOT / "build"
DEFAULT_PAGES_DIR = PROJECT_ROOT / "build" / "pages"
DEFAULT_PIPELINE_REPORT_PATH = PROJECT_ROOT / "build" / "pipeline_report.json"

T = TypeVar("T")


class PipelineError(RuntimeError):
    """A user-facing full-pipeline failure with stage context."""


@dataclass(frozen=True)
class PipelineSummary:
    outline_path: Path
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
    pdf_path: str | Path,
    *,
    paper_title: str,
    omit_front_page: bool = False,
    use_existing_outline: bool = False,
    outline_path: str | Path | None = None,
    ai_layout_path: str | Path | None = None,
    visual_requirements_path: str | Path | None = None,
    qspec_path: str | Path | None = None,
    build_dir: str | Path | None = None,
    pages_dir: str | Path | None = None,
    dpi: int = DEFAULT_DPI,
    report_path: str | Path | None = None,
    alignment_tolerance_mm: float = DEFAULT_ALIGNMENT_TOLERANCE_MM,
    max_alignment_passes: int = DEFAULT_MAX_ALIGNMENT_PASSES,
) -> PipelineSummary:
    """Run the structural reference-PDF to answer-card preview pipeline."""

    resolved_outline_path = Path(outline_path) if outline_path is not None else DEFAULT_OUTLINE_PATH
    resolved_ai_layout_path = Path(ai_layout_path) if ai_layout_path is not None else DEFAULT_AI_LAYOUT_PATH
    resolved_build_dir = Path(build_dir) if build_dir is not None else DEFAULT_BUILD_DIR
    resolved_visual_requirements_path = (
        Path(visual_requirements_path)
        if visual_requirements_path is not None
        else (
            resolved_build_dir / "visual_requirements.json"
            if build_dir is not None
            else DEFAULT_VISUAL_REQUIREMENTS_PATH
        )
    )
    resolved_qspec_path = Path(qspec_path) if qspec_path is not None else DEFAULT_QSPEC_PATH
    resolved_pages_dir = Path(pages_dir) if pages_dir is not None else DEFAULT_PAGES_DIR
    resolved_report_path = (
        Path(report_path) if report_path is not None else resolved_outline_path.parent / "pipeline_report.json"
    )
    timer = PipelineTimer(resolved_report_path)
    if timer.data.get("status") != "running":
        timer.begin(label=paper_title, reset=True)
    elif not timer.data.get("label"):
        timer.begin(label=paper_title, reset=False)
    timer.update_configuration(
        {
            "alignment_tolerance_mm": alignment_tolerance_mm,
            "default_alignment_tolerance_mm": DEFAULT_ALIGNMENT_TOLERANCE_MM,
            "max_alignment_passes": max_alignment_passes,
            "default_max_alignment_passes": DEFAULT_MAX_ALIGNMENT_PASSES,
        }
    )

    if use_existing_outline:
        written_outline = _run_stage(
            "reuse_existing_outline",
            _require_existing_outline,
            resolved_outline_path,
            timer=timer,
        )
    else:
        written_outline = _run_stage(
            "extract_outline",
            extract_outline,
            pdf_path,
            resolved_outline_path,
            timer=timer,
        )
    outline_counts = _run_stage(
        "read_outline_summary", _read_outline_counts, written_outline, timer=timer
    )

    _run_stage("require_ai_layout", _require_ai_layout, resolved_ai_layout_path, timer=timer)
    handoff_audit = _run_stage(
        "audit_ai_layout_handoff",
        audit_ai_layout_handoff,
        written_outline,
        resolved_ai_layout_path,
        timer=timer,
    )
    timer.update_result(handoff_audit)
    _run_stage(
        "reject_ai_layout_conflicts",
        _reject_ai_layout_conflicts,
        handoff_audit,
        timer=timer,
    )
    validated_ai_layout = _run_stage(
        "validate_ai_layout",
        load_ai_layout,
        resolved_ai_layout_path,
        timer=timer,
    )
    timer.update_result(_percent_source_report(validated_ai_layout))
    written_visual_requirements = _run_stage(
        "export_visual_requirements",
        export_visual_requirements,
        resolved_ai_layout_path,
        resolved_visual_requirements_path,
        timer=timer,
    )
    written_qspec = _run_stage(
        "ai_layout_to_qspec",
        ai_layout_to_qspec,
        written_outline,
        resolved_ai_layout_path,
        resolved_qspec_path,
        paper_title=paper_title,
        omit_front_page=omit_front_page,
        timer=timer,
    )
    try:
        pdf_output = _run_stage(
            "build_answer_card",
            build_answer_card,
            written_qspec,
            build_dir=resolved_build_dir,
            align_pages=True,
            alignment_tolerance_mm=alignment_tolerance_mm,
            max_alignment_passes=max_alignment_passes,
            timer=timer,
        )
    except PipelineError:
        _record_alignment_history(
            timer,
            resolved_build_dir / "frame_alignment.json",
            alignment_tolerance_mm,
        )
        raise
    _record_alignment_history(
        timer,
        resolved_build_dir / "frame_alignment.json",
        alignment_tolerance_mm,
    )
    preview_outputs = _run_stage(
        "render_pdf_pages",
        render_pdf_pages,
        pdf_output,
        resolved_pages_dir,
        dpi=dpi,
        timer=timer,
    )

    summary = PipelineSummary(
        outline_path=Path(written_outline),
        visual_requirements_path=Path(written_visual_requirements),
        qspec_path=Path(written_qspec),
        pdf_path=Path(pdf_output),
        preview_dir=resolved_pages_dir,
        preview_paths=[Path(path) for path in preview_outputs],
        question_count=outline_counts[0],
        item_count=outline_counts[1],
        report_path=resolved_report_path,
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
        if timer is not None:
            return timer.run(stage, func, *args, **kwargs)
        return func(*args, **kwargs)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PipelineError(f"{stage} failed: {exc}") from exc


def _record_alignment_history(
    timer: PipelineTimer,
    report_path: Path,
    tolerance_mm: float,
) -> None:
    if not report_path.is_file():
        return
    try:
        history = load_alignment_pass_summaries(
            report_path,
            tolerance_mm=tolerance_mm,
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return
    timer.update_result({"alignment_history": history})


def _read_outline_counts(outline_path: str | Path) -> tuple[int, int]:
    with Path(outline_path).open("r", encoding="utf-8") as outline_file:
        outline = json.load(outline_file)

    if not isinstance(outline, dict):
        raise ValueError("outline must be a JSON object")

    questions = outline.get("questions", [])
    if not isinstance(questions, list):
        raise ValueError("outline questions must be a list")

    item_count = 0
    for question in questions:
        if not isinstance(question, dict):
            continue
        items = question.get("items", [])
        if isinstance(items, list):
            item_count += len(items)

    return len(questions), item_count


def _require_ai_layout(ai_layout_path: str | Path) -> Path:
    path = Path(ai_layout_path)
    if not path.exists():
        raise ValueError(
            f"AI layout is required and was not found: {path}. "
            f"Create build/ai_layout.json from AI inspection using {DEFAULT_AI_LAYOUT_PROMPT_PATH} "
            "before generating qspec."
        )
    return path


def _require_existing_outline(outline_path: str | Path) -> Path:
    path = Path(outline_path)
    if not path.is_file():
        raise ValueError(f"frozen outline does not exist: {path}")
    return path


def _percent_source_report(ai_layout: dict[str, object]) -> dict[str, object]:
    questions = ai_layout.get("questions")
    if not isinstance(questions, list):
        return {"derived_percent_question_ids": []}
    derived = [
        str(question.get("id"))
        for question in questions
        if isinstance(question, dict) and question.get("percent_source") == "derived"
    ]
    return {"derived_percent_question_ids": derived}


def _reject_ai_layout_conflicts(audit: dict[str, object]) -> None:
    conflicts = audit.get("ai_layout_conflicts")
    if isinstance(conflicts, list) and conflicts:
        codes = sorted(
            {
                str(conflict.get("code"))
                for conflict in conflicts
                if isinstance(conflict, dict) and conflict.get("code")
            }
        )
        raise ValueError(
            "AI layout conflicts with the structural outline: " + ", ".join(codes)
        )


def run_artifact_sanity_checks(summary: PipelineSummary) -> None:
    """Run lightweight checks over final full-pipeline artifacts."""

    failures: list[str] = []
    failures.extend(_check_preview_files(summary.preview_paths))
    failures.extend(_check_log_keywords(summary.pdf_path.parent / "answercard.log"))
    failures.extend(_check_qspec_sanity(summary.qspec_path))
    failures.extend(_check_pdf_sanity(summary.pdf_path))

    if failures:
        raise ValueError("; ".join(failures))


def _check_preview_files(preview_paths: list[Path]) -> list[str]:
    failures: list[str] = []
    if not preview_paths:
        return ["preview_paths is empty"]

    for preview_path in preview_paths:
        if not preview_path.exists():
            failures.append(f"preview missing: {preview_path}")
        elif preview_path.stat().st_size <= 0:
            failures.append(f"preview empty: {preview_path}")
    return failures


def _check_log_keywords(log_path: Path) -> list[str]:
    if not log_path.exists():
        return []

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    blocked_keywords = ("Overfull \\vbox", "Fatal error", "Emergency stop")
    found = [keyword for keyword in blocked_keywords if keyword in log_text]
    if not found:
        return []
    return [f"{log_path} contains blocked LaTeX log keyword(s): {', '.join(found)}"]


def _check_qspec_sanity(qspec_path: Path) -> list[str]:
    spec = load_spec(qspec_path)
    empty_scored_ids = []
    for question in spec.questions:
        if _positive_number(question.score) and not question.blocks:
            empty_scored_ids.append(question.id)

    if empty_scored_ids:
        return ["scored questions must have at least one block: " + ", ".join(empty_scored_ids)]
    return []


def _check_pdf_sanity(pdf_path: Path) -> list[str]:
    failures: list[str] = []
    if not pdf_path.exists():
        return [f"PDF missing: {pdf_path}"]
    if pdf_path.stat().st_size <= 0:
        return [f"PDF empty: {pdf_path}"]

    pdf_inspection = _inspect_pdf_first_page(pdf_path)
    if pdf_inspection is None:
        return failures

    page_count, first_page_text = pdf_inspection
    if page_count <= 0:
        failures.append(f"PDF has no pages: {pdf_path}")
    if not first_page_text.strip():
        failures.append(f"PDF first page text is empty: {pdf_path}")
    return failures


def _inspect_pdf_first_page(pdf_path: Path) -> tuple[int, str] | None:
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError:
        return None

    with fitz.open(pdf_path) as document:
        page_count = document.page_count
        first_page_text = ""
        if page_count > 0:
            first_page_text = document.load_page(0).get_text()
    return page_count, first_page_text


def _positive_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def format_summary(summary: PipelineSummary) -> str:
    lines = [
        "summary:",
        f"  outline: {summary.outline_path}",
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
    parser = argparse.ArgumentParser(
        description="Run reference PDF structure extraction through answer-card PDF previews."
    )
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("--paper-title", required=True)
    parser.add_argument("--omit-front-page", action="store_true")
    parser.add_argument("--use-existing-outline", action="store_true")
    parser.add_argument("--outline-path", type=Path, default=None)
    parser.add_argument("--ai-layout-path", type=Path, default=None)
    parser.add_argument("--visual-requirements-path", type=Path, default=None)
    parser.add_argument("--qspec-path", type=Path, default=None)
    parser.add_argument("--build-dir", type=Path, default=None)
    parser.add_argument("--pages-dir", type=Path, default=None)
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument(
        "--alignment-tolerance-mm",
        type=float,
        default=DEFAULT_ALIGNMENT_TOLERANCE_MM,
    )
    parser.add_argument(
        "--max-alignment-passes",
        type=int,
        default=DEFAULT_MAX_ALIGNMENT_PASSES,
    )
    args = parser.parse_args(argv)

    try:
        summary = run_full_pipeline(
            args.pdf_path,
            paper_title=args.paper_title,
            omit_front_page=args.omit_front_page,
            use_existing_outline=args.use_existing_outline,
            outline_path=args.outline_path,
            ai_layout_path=args.ai_layout_path,
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
