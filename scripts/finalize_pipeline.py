from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Callable, TypeVar


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from answercard.layout import plan_answer_pages
from answercard.frame_alignment import DEFAULT_ALIGNMENT_TOLERANCE_MM
from answercard.pipeline_timing import PipelineTimer
from answercard.schema import AnswerCardSpec, load_spec
from answercard.visual_requirements import (
    load_visual_requirements,
    visual_requirement_counts,
    visual_requirement_report_data,
)
from pypdf import PdfReader


DEFAULT_QSPEC_PATH = PROJECT_ROOT / "spec" / "qspec.draft.yaml"
DEFAULT_BUILD_DIR = PROJECT_ROOT / "build"
DEFAULT_TEX_NAME = "answercard.tex"
DEFAULT_PDF_PATH = DEFAULT_BUILD_DIR / "answercard.pdf"
DEFAULT_PAGES_DIR = DEFAULT_BUILD_DIR / "pages"
DEFAULT_ALIGNMENT_REPORT = DEFAULT_BUILD_DIR / "frame_alignment.json"
DEFAULT_VISUAL_REQUIREMENTS = DEFAULT_BUILD_DIR / "visual_requirements.json"
DEFAULT_PIPELINE_REPORT = DEFAULT_BUILD_DIR / "pipeline_report.json"
DEFAULT_LOG_PATHS = (
    DEFAULT_BUILD_DIR / "answercard.log",
)

FORBIDDEN_PDF_TERMS = ("参考答案", "答案及评分标准")
BLOCKED_LOG_TERMS = (
    "Overfull \\vbox",
    "Fatal error",
    "Emergency stop",
    "! LaTeX Error",
)
PAGE_NUMBER_TEX_MARKERS = (
    r"\pagestyle{answercard}",
    r"\QuestionTitleFont\thepage",
)

T = TypeVar("T")


class FinalizePipelineError(RuntimeError):
    """A final validation, cleanup, or artifact-retention failure."""


def finalize_pipeline(
    *,
    qspec_path: str | Path = DEFAULT_QSPEC_PATH,
    pdf_path: str | Path = DEFAULT_PDF_PATH,
    pages_dir: str | Path = DEFAULT_PAGES_DIR,
    build_dir: str | Path = DEFAULT_BUILD_DIR,
    alignment_report_path: str | Path = DEFAULT_ALIGNMENT_REPORT,
    visual_requirements_path: str | Path = DEFAULT_VISUAL_REQUIREMENTS,
    report_path: str | Path = DEFAULT_PIPELINE_REPORT,
    log_paths: tuple[str | Path, ...] = DEFAULT_LOG_PATHS,
    front_pages: int = 0,
    temp_paths: tuple[str | Path, ...] = (),
    alignment_tolerance_mm: float = DEFAULT_ALIGNMENT_TOLERANCE_MM,
    temp_root: str | Path | None = None,
    prune_on_success: bool = False,
) -> dict[str, Any]:
    """Validate artifacts, always clean temp evidence, and optionally prune on success."""

    if front_pages < 0:
        raise ValueError("front_pages must be zero or greater")
    if alignment_tolerance_mm < 0:
        raise ValueError("alignment_tolerance_mm must be zero or greater")

    qspec = Path(qspec_path)
    pdf = Path(pdf_path)
    previews = Path(pages_dir)
    build = Path(build_dir)
    tex = build / DEFAULT_TEX_NAME
    alignment_report = Path(alignment_report_path)
    visual_requirements = Path(visual_requirements_path)
    report_file = Path(report_path)
    logs = tuple(Path(path) for path in log_paths)
    resolved_temp_root = Path(temp_root) if temp_root is not None else PROJECT_ROOT / ".tmp"
    resolved_temp_root.mkdir(parents=True, exist_ok=True)

    timer = PipelineTimer(report_file)
    timer.ensure_running(reset_if_finished=False)
    report = timer.data
    report["finalization_inputs"] = {
            "qspec": str(qspec),
            "tex": str(tex),
            "pdf": str(pdf),
            "pages_dir": str(previews),
            "alignment_report": str(alignment_report),
            "visual_requirements": str(visual_requirements),
            "logs": [str(path) for path in logs],
            "front_pages": front_pages,
            "alignment_tolerance_mm": alignment_tolerance_mm,
            "default_alignment_tolerance_mm": DEFAULT_ALIGNMENT_TOLERANCE_MM,
    }
    timer.update_result({})
    internal_workspace = tempfile.TemporaryDirectory(
        prefix="answercard-final-check-",
        dir=resolved_temp_root,
    )
    failure: Exception | None = None

    try:
        spec = _run_stage(timer, "validate_qspec", load_spec, qspec)
        visual_result = _run_stage(
            timer,
            "validate_visual_requirements",
            _validate_visual_requirements_for_spec,
            visual_requirements,
            spec,
        )
        expected_body_pages = _run_stage(timer, "plan_expected_body_pages", _planned_page_count, spec)
        expected_total_pages = expected_body_pages + front_pages
        page_number_result = _run_stage(
            timer,
            "validate_page_number_rule",
            _validate_page_number_rule,
            tex,
        )
        pdf_result = _run_stage(
            timer,
            "validate_pdf",
            _validate_pdf,
            pdf,
            expected_total_pages=expected_total_pages,
        )
        _run_stage(timer, "validate_compile_logs", _validate_compile_logs, logs)
        alignment_result = _run_stage(
            timer,
            "validate_alignment_report",
            _validate_alignment_report,
            alignment_report,
            expected_body_pages=expected_body_pages,
            tolerance_mm=alignment_tolerance_mm,
        )
        preview_result = _run_stage(
            timer,
            "validate_previews",
            _validate_previews,
            previews,
            expected_count=expected_total_pages,
        )
        timer.update_result({
            "expected_body_pages": expected_body_pages,
            "front_pages": front_pages,
            "printed_percent_total": sum(question.percent for question in spec.questions),
            "final_pdf_pages": pdf_result["page_count"],
            "preview_count": preview_result["preview_count"],
            "page_number_rule": page_number_result["rule"],
            "alignment_pass": alignment_result["pass"],
            "top_spread_mm": alignment_result["top_spread_mm"],
            "bottom_spread_mm": alignment_result["bottom_spread_mm"],
            "alignment_tolerance_mm": alignment_tolerance_mm,
            "default_alignment_tolerance_mm": DEFAULT_ALIGNMENT_TOLERANCE_MM,
            "visual_requirement_counts": visual_requirement_counts(visual_result),
            **visual_requirement_report_data(visual_result),
        })
    except Exception as exc:
        failure = exc
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        cleanup_error = _cleanup_temporary_artifacts(
            timer,
            internal_workspace,
            temp_paths=tuple(Path(path) for path in temp_paths),
            temp_root=resolved_temp_root,
        )
        if cleanup_error is not None and failure is None:
            failure = cleanup_error
            report["status"] = "failed"
            report["error"] = f"{type(cleanup_error).__name__}: {cleanup_error}"

    if failure is None and prune_on_success:
        try:
            _run_stage(
                timer,
                "prune_build_artifacts",
                _prune_build_artifacts,
                build,
                keep_paths=(
                    build / DEFAULT_TEX_NAME,
                    pdf,
                    previews,
                    alignment_report,
                    visual_requirements,
                    report_file,
                    qspec,
                ),
            )
        except Exception as exc:
            failure = exc
            report["status"] = "failed"
            report["error"] = f"{type(exc).__name__}: {exc}"

    if failure is None:
        timer.update_result({"build_artifacts_pruned": prune_on_success})

    timer.finish(status="failed" if failure is not None else "passed")

    if failure is not None:
        raise FinalizePipelineError(str(failure)) from failure
    return report


def _run_stage(
    timer: PipelineTimer,
    name: str,
    func: Callable[..., T],
    *args: object,
    **kwargs: object,
) -> T:
    return timer.run(name, func, *args, **kwargs)


def _planned_page_count(spec: AnswerCardSpec) -> int:
    page_count = len(plan_answer_pages(spec))
    if page_count < 1:
        raise ValueError("qspec pagination produced no body pages")
    return page_count


def _validate_page_number_rule(tex_path: Path) -> dict[str, str]:
    if not tex_path.is_file():
        raise ValueError(f"generated LaTeX is missing: {tex_path}")
    tex = tex_path.read_text(encoding="utf-8", errors="replace")
    missing = [marker for marker in PAGE_NUMBER_TEX_MARKERS if marker not in tex]
    if missing:
        raise ValueError(
            "generated LaTeX is missing the required centered page-number rule: "
            + ", ".join(missing)
        )
    return {"rule": "bottom_center_question_title_font"}


def _validate_visual_requirements_for_spec(
    path: Path,
    spec: AnswerCardSpec,
) -> dict[str, Any]:
    expected_item_ids = [
        block.id
        for question in spec.questions
        for block in question.blocks
    ]
    return load_visual_requirements(path, expected_item_ids=expected_item_ids)


def _validate_pdf(pdf_path: Path, *, expected_total_pages: int) -> dict[str, Any]:
    if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
        raise ValueError(f"final PDF is missing or empty: {pdf_path}")
    reader = PdfReader(pdf_path)
    if len(reader.pages) != expected_total_pages:
        raise ValueError(
            f"final PDF page count must be {expected_total_pages}, got {len(reader.pages)}"
        )

    extracted_text: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        if abs(width - 595.28) > 1.0 or abs(height - 841.89) > 1.0:
            raise ValueError(
                f"final PDF page {page_number} is not A4: {width:.2f} x {height:.2f} pt"
            )
        extracted_text.append(page.extract_text() or "")

    combined_text = "\n".join(extracted_text)
    found_terms = [term for term in FORBIDDEN_PDF_TERMS if term in combined_text]
    if found_terms:
        raise ValueError("final PDF contains forbidden sensitive phrase(s): " + ", ".join(found_terms))
    return {"page_count": len(reader.pages)}


def _validate_compile_logs(log_paths: tuple[Path, ...]) -> dict[str, Any]:
    existing_logs = [path for path in log_paths if path.exists()]
    if not existing_logs:
        raise ValueError("no compilation log was found")
    failures: list[str] = []
    for log_path in existing_logs:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        found = [term for term in BLOCKED_LOG_TERMS if term in log_text]
        if found:
            failures.append(f"{log_path}: {', '.join(found)}")
    if failures:
        raise ValueError("compilation log contains blocked error(s): " + "; ".join(failures))
    return {"checked_logs": [str(path) for path in existing_logs]}


def _validate_alignment_report(
    report_path: Path,
    *,
    expected_body_pages: int,
    tolerance_mm: float,
) -> dict[str, Any]:
    if not report_path.exists():
        raise ValueError(f"alignment report is missing: {report_path}")
    data = json.loads(report_path.read_text(encoding="utf-8"))
    passes = data.get("passes") if isinstance(data, dict) else None
    if not isinstance(passes, list) or not passes:
        raise ValueError("alignment report must contain at least one pass")
    final_pass = passes[-1]
    if not isinstance(final_pass, dict):
        raise ValueError("alignment report final pass must be an object")
    pages = final_pass.get("pages")
    if not isinstance(pages, list) or len(pages) != expected_body_pages:
        actual = len(pages) if isinstance(pages, list) else 0
        raise ValueError(
            f"alignment report must contain {expected_body_pages} body pages, got {actual}"
        )
    top_spread = _report_number(final_pass, "top_spread_mm")
    bottom_spread = _report_number(final_pass, "bottom_spread_mm")
    if top_spread > tolerance_mm or bottom_spread > tolerance_mm:
        raise ValueError(
            f"alignment spread exceeds {tolerance_mm:.3f}mm: "
            f"top={top_spread:.3f}mm, bottom={bottom_spread:.3f}mm"
        )
    return {
        "pass": final_pass.get("pass"),
        "top_spread_mm": top_spread,
        "bottom_spread_mm": bottom_spread,
    }


def _validate_previews(pages_dir: Path, *, expected_count: int) -> dict[str, Any]:
    if not pages_dir.is_dir():
        raise ValueError(f"preview directory is missing: {pages_dir}")
    preview_paths = sorted(pages_dir.glob("page-*.png"))
    expected_names = [f"page-{page:03d}.png" for page in range(1, expected_count + 1)]
    actual_names = [path.name for path in preview_paths]
    if actual_names != expected_names:
        raise ValueError(
            f"preview files must be exactly {expected_names}, got {actual_names}"
        )
    empty = [str(path) for path in preview_paths if path.stat().st_size <= 0]
    if empty:
        raise ValueError("preview files are empty: " + ", ".join(empty))
    return {"preview_count": len(preview_paths)}


def _cleanup_temporary_artifacts(
    timer: PipelineTimer,
    workspace: tempfile.TemporaryDirectory[str],
    *,
    temp_paths: tuple[Path, ...],
    temp_root: Path,
) -> Exception | None:
    stage_id = timer.start_stage("cleanup_temporary_artifacts")
    try:
        resolved_root = temp_root.resolve()
        for temp_path in temp_paths:
            if not temp_path.exists():
                continue
            resolved_path = temp_path.resolve()
            if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
                raise ValueError(f"refusing to clean path outside .tmp: {resolved_path}")
            if resolved_path.is_dir():
                shutil.rmtree(resolved_path)
            else:
                resolved_path.unlink()
        workspace.cleanup()
    except Exception as exc:
        timer.stop_stage(
            stage_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        return exc
    timer.stop_stage(
        stage_id,
        status="passed",
        details={"removed_paths": [str(path) for path in temp_paths]},
    )
    return None


def _prune_build_artifacts(build_dir: Path, *, keep_paths: tuple[Path, ...]) -> list[str]:
    if not build_dir.is_dir():
        raise ValueError(f"build directory is missing: {build_dir}")
    resolved_build = build_dir.resolve()
    resolved_keeps = [path.resolve() for path in keep_paths]
    removed: list[str] = []
    for child in build_dir.iterdir():
        resolved_child = child.resolve()
        if resolved_child == resolved_build or resolved_build not in resolved_child.parents:
            raise ValueError(f"refusing to prune path outside build: {resolved_child}")
        if any(
            keep == resolved_child or resolved_child in keep.parents
            for keep in resolved_keeps
        ):
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed.append(str(child))
    return removed


def _report_number(data: dict[str, Any], key: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"alignment report {key} must be numeric")
    return float(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate final answer-card artifacts, clean temp evidence, and prune build outputs."
    )
    parser.add_argument("--qspec", type=Path, default=DEFAULT_QSPEC_PATH)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF_PATH)
    parser.add_argument("--pages-dir", type=Path, default=DEFAULT_PAGES_DIR)
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR)
    parser.add_argument("--alignment-report", type=Path, default=DEFAULT_ALIGNMENT_REPORT)
    parser.add_argument("--visual-requirements", type=Path, default=DEFAULT_VISUAL_REQUIREMENTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_PIPELINE_REPORT)
    parser.add_argument("--log", action="append", type=Path, default=None)
    parser.add_argument("--front-pages", type=int, default=0)
    parser.add_argument("--temp-path", action="append", type=Path, default=[])
    parser.add_argument(
        "--prune-on-success",
        action="store_true",
        help="Remove non-delivery files after validation. Disabled by default so audit artifacts remain available.",
    )
    parser.add_argument(
        "--alignment-tolerance-mm",
        type=float,
        default=DEFAULT_ALIGNMENT_TOLERANCE_MM,
    )
    args = parser.parse_args(argv)

    logs = tuple(args.log) if args.log else DEFAULT_LOG_PATHS
    try:
        report = finalize_pipeline(
            qspec_path=args.qspec,
            pdf_path=args.pdf,
            pages_dir=args.pages_dir,
            build_dir=args.build_dir,
            alignment_report_path=args.alignment_report,
            visual_requirements_path=args.visual_requirements,
            report_path=args.report,
            log_paths=logs,
            front_pages=args.front_pages,
            temp_paths=tuple(args.temp_path),
            alignment_tolerance_mm=args.alignment_tolerance_mm,
            prune_on_success=args.prune_on_success,
        )
    except (FinalizePipelineError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    result = report["result"]
    print("summary:")
    print(f"  pdf_pages: {result['final_pdf_pages']}")
    print(f"  previews: {result['preview_count']}")
    print(f"  report: {args.report}")
    print("  temp_cleanup: passed")
    print(f"  build_prune: {'passed' if args.prune_on_success else 'skipped'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
