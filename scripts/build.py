from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from answercard.render_tex import render_tex
from answercard.frame_alignment import (
    DEFAULT_ALIGNMENT_TOLERANCE_MM,
    DEFAULT_MAX_ALIGNMENT_PASSES,
    alignment_corrections,
    alignment_spreads,
    measure_pdf_frames,
)
from answercard.layout import PlannedPage, plan_answer_pages
from answercard.schema import load_spec


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUILD_DIR = PROJECT_ROOT / "build"
DEFAULT_TEX_NAME = "answercard.tex"
DEFAULT_PDF_NAME = "answercard.pdf"
DEFAULT_LOG_NAME = "build.log"


class BuildError(RuntimeError):
    """A user-facing build failure."""


def build_answer_card(
    spec_path: str | Path,
    *,
    build_dir: str | Path = DEFAULT_BUILD_DIR,
    xelatex: str = "xelatex",
    align_pages: bool = False,
    max_alignment_passes: int = DEFAULT_MAX_ALIGNMENT_PASSES,
    alignment_tolerance_mm: float = DEFAULT_ALIGNMENT_TOLERANCE_MM,
    image_bindings: Mapping[str, Mapping[str, Any]] | None = None,
) -> Path:
    """Validate qspec, render LaTeX, compile it with xelatex, and return the PDF path."""

    destination_dir = Path(build_dir)
    tex_path = destination_dir / DEFAULT_TEX_NAME
    pdf_path = destination_dir / DEFAULT_PDF_NAME

    render_tex(spec_path, tex_path, image_bindings=image_bindings)
    _compile_tex(tex_path, pdf_path, destination_dir, xelatex=xelatex)
    if align_pages:
        _align_compiled_pages(
            spec_path,
            tex_path,
            pdf_path,
            destination_dir,
            xelatex=xelatex,
            max_passes=max_alignment_passes,
            tolerance_mm=alignment_tolerance_mm,
            image_bindings=image_bindings,
        )
    return pdf_path


def _align_compiled_pages(
    spec_path: str | Path,
    tex_path: Path,
    pdf_path: Path,
    build_dir: Path,
    *,
    xelatex: str,
    max_passes: int,
    tolerance_mm: float,
    image_bindings: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    spec = load_spec(spec_path)
    current_plan = plan_answer_pages(spec)
    expected_body_page_count = len(current_plan)
    front_page_count = 0 if spec.paper.omit_front_page else 1
    block_height_adjustments: dict[str, float] = {}
    page_top_spacers = [0.0] * expected_body_page_count
    report: list[dict[str, object]] = []
    alignment_target_mm: float | None = None
    _write_alignment_report(build_dir, report)

    for pass_number in range(max_passes + 1):
        measurements = measure_pdf_frames(pdf_path, skip_pages=front_page_count)
        expected_total_page_count = expected_body_page_count + front_page_count
        if len(measurements) != expected_body_page_count:
            raise BuildError(
                f"page alignment expected {expected_body_page_count} body pages and "
                f"{expected_total_page_count} total pages but measured "
                f"{len(measurements)} body pages"
            )

        top_spread, bottom_spread = alignment_spreads(
            measurements,
            include_last_bottom=False,
        )
        _all_top_spread, all_bottom_spread = alignment_spreads(measurements)
        if alignment_target_mm is None:
            alignment_target_mm = max(
                measurement.top_from_page_top_mm for measurement in measurements
            )
        report.append(
            {
                "pass": pass_number,
                "top_spread_mm": round(top_spread, 3),
                "bottom_spread_mm": round(bottom_spread, 3),
                "bottom_spread_all_pages_mm": round(all_bottom_spread, 3),
                "pages": [
                    {
                        "page": measurement.page,
                        "top_from_page_top_mm": round(measurement.top_from_page_top_mm, 3),
                        "bottom_from_page_bottom_mm": round(measurement.bottom_from_page_bottom_mm, 3),
                    }
                    for measurement in measurements
                ],
            }
        )
        _write_alignment_report(build_dir, report)
        if top_spread <= tolerance_mm and bottom_spread <= tolerance_mm:
            return
        if pass_number == max_passes:
            raise BuildError(
                f"page alignment did not converge within {max_passes} correction passes: "
                f"top spread {top_spread:.2f}mm, bottom spread {bottom_spread:.2f}mm"
            )

        height_delta, top_delta = alignment_corrections(
            measurements,
            target_mm=alignment_target_mm,
        )
        height_delta[-1] = 0.0
        for planned_page, delta in zip(current_plan, height_delta, strict=True):
            page_blocks = [
                planned_block
                for planned_question in planned_page.questions
                for planned_block in planned_question.blocks
            ]
            if not page_blocks or abs(delta) <= 0.001:
                continue
            delta_per_block = delta / len(page_blocks)
            for planned_block in page_blocks:
                block_id = planned_block.block.id
                block_height_adjustments[block_id] = (
                    block_height_adjustments.get(block_id, 0.0) + delta_per_block
                )

        next_plan = plan_answer_pages(
            spec,
            block_height_adjustments_mm=block_height_adjustments,
        )
        if _page_signatures(next_plan) == _page_signatures(current_plan):
            page_top_spacers = [
                max(0.0, current + delta)
                for current, delta in zip(page_top_spacers, top_delta, strict=True)
            ]
        else:
            # A real repagination invalidates page-indexed top spacers.  Keep
            # the per-block height corrections, reset the page-local spacers,
            # and measure the new layout afresh on the next bounded pass.
            page_top_spacers = [0.0] * len(next_plan)
            alignment_target_mm = None

        current_plan = next_plan
        expected_body_page_count = len(current_plan)
        render_tex(
            spec_path,
            tex_path,
            block_height_adjustments_mm=block_height_adjustments,
            page_top_spacers_mm=page_top_spacers,
            image_bindings=image_bindings,
        )
        _compile_tex(tex_path, pdf_path, build_dir, xelatex=xelatex)


def _page_signatures(pages: list[PlannedPage]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(
            planned_block.block.id
            for planned_question in page.questions
            for planned_block in planned_question.blocks
        )
        for page in pages
    )


def _write_alignment_report(build_dir: Path, report: list[dict[str, object]]) -> Path:
    report_path = build_dir / "frame_alignment.json"
    report_path.write_text(json.dumps({"passes": report}, indent=2) + "\n", encoding="utf-8")
    return report_path


def _compile_tex(tex_path: Path, pdf_path: Path, build_dir: Path, *, xelatex: str) -> None:
    command = [
        xelatex,
        "-interaction=nonstopmode",
        "-halt-on-error",
        tex_path.name,
    ]

    try:
        pdf_path.unlink(missing_ok=True)
    except PermissionError as exc:
        raise BuildError(
            f"Cannot replace {pdf_path}. Close any PDF viewer using this file and retry."
        ) from exc

    try:
        result = subprocess.run(
            command,
            cwd=build_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise BuildError(
            "xelatex was not found. Install a TeX distribution such as TeX Live or MiKTeX, "
            "or add xelatex to PATH."
        ) from exc

    if result.returncode != 0:
        _write_build_log(build_dir, command, result.stdout, result.stderr)
        raise BuildError(
            f"xelatex failed with exit code {result.returncode}. "
            f"See {build_dir / DEFAULT_LOG_NAME} for details."
        )

    if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
        _write_build_log(build_dir, command, result.stdout, result.stderr)
        raise BuildError(
            f"xelatex finished without a usable new PDF at {pdf_path}. "
            f"See {build_dir / DEFAULT_LOG_NAME} for details."
        )


def _write_build_log(build_dir: Path, command: list[str], stdout: str, stderr: str) -> Path:
    log_path = build_dir / DEFAULT_LOG_NAME
    log_path.write_text(
        "\n".join(
            [
                "$ " + " ".join(command),
                "",
                "=== stdout ===",
                stdout,
                "=== stderr ===",
                stderr,
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    return log_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build qspec.yaml into build/answercard.pdf.")
    parser.add_argument("spec_path", type=Path)
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR)
    parser.add_argument("--align-pages", action="store_true")
    args = parser.parse_args(argv)

    try:
        pdf_path = build_answer_card(
            args.spec_path,
            build_dir=args.build_dir,
            align_pages=args.align_pages,
        )
    except (BuildError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(pdf_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
