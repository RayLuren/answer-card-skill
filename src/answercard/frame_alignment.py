"""Pixel-based frame measurements for answer-card page alignment."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


DEFAULT_ALIGNMENT_TOLERANCE_MM = 1.1
DEFAULT_MAX_ALIGNMENT_PASSES = 3


@dataclass(frozen=True)
class FrameMeasurement:
    page: int
    top_from_page_top_mm: float
    bottom_from_page_bottom_mm: float


def load_alignment_pass_summaries(
    report_path: str | Path,
    *,
    tolerance_mm: float,
) -> list[dict[str, Any]]:
    """Load answer-free per-pass alignment summaries for durable reporting."""

    if tolerance_mm < 0:
        raise ValueError("tolerance_mm must be zero or greater")
    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    passes = data.get("passes") if isinstance(data, dict) else None
    if not isinstance(passes, list) or not passes:
        raise ValueError("alignment report must contain at least one pass")

    tolerance = round(float(tolerance_mm), 3)
    summaries: list[dict[str, Any]] = []
    for index, entry in enumerate(passes):
        if not isinstance(entry, dict):
            raise ValueError(f"alignment report pass {index} must be an object")
        pass_number = entry.get("pass")
        if isinstance(pass_number, bool) or not isinstance(pass_number, int):
            raise ValueError(f"alignment report pass {index} must have an integer pass number")
        top_spread = _report_number(entry, "top_spread_mm", index=index)
        bottom_spread = _report_number(entry, "bottom_spread_mm", index=index)
        summaries.append(
            {
                "pass": pass_number,
                "top_spread_mm": top_spread,
                "bottom_spread_mm": bottom_spread,
                "tolerance_mm": tolerance,
                "passed": top_spread <= tolerance_mm and bottom_spread <= tolerance_mm,
            }
        )
    return summaries


def measure_pdf_frames(
    pdf_path: str | Path,
    *,
    dpi: int = 200,
    black_threshold: int = 80,
    row_ratio: float = 0.5,
    skip_pages: int = 0,
) -> list[FrameMeasurement]:
    """Return frame-line measurements after skipping non-body front pages."""

    if skip_pages < 0:
        raise ValueError("skip_pages must be zero or greater")

    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for page alignment.") from exc

    measurements: list[FrameMeasurement] = []
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    with fitz.open(pdf_path) as document:
        if skip_pages >= document.page_count:
            raise ValueError("skip_pages must leave at least one body page to measure")
        for page_index in range(skip_pages, document.page_count):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            minimum_black = int(pixmap.width * row_ratio)
            dark_rows = _dark_row_indices(
                pixmap.samples,
                width=pixmap.width,
                height=pixmap.height,
                channels=pixmap.n,
                threshold=black_threshold,
                minimum_black=minimum_black,
            )
            if not dark_rows:
                raise ValueError(f"no horizontal frame line detected on page {page_index + 1}")

            page_height_mm = page.rect.height * 25.4 / 72
            mm_per_pixel = page_height_mm / pixmap.height
            measurements.append(
                FrameMeasurement(
                    page=page_index + 1,
                    top_from_page_top_mm=dark_rows[0] * mm_per_pixel,
                    bottom_from_page_bottom_mm=page_height_mm - dark_rows[-1] * mm_per_pixel,
                )
            )
    return measurements


def alignment_corrections(
    measurements: list[FrameMeasurement],
    *,
    target_mm: float | None = None,
) -> tuple[list[float], list[float]]:
    """Calculate top spacers and total row-height growth for the next pass."""

    if not measurements:
        raise ValueError("frame measurements are empty")

    target = target_mm if target_mm is not None else max(
        measurement.top_from_page_top_mm for measurement in measurements
    )
    top_spacers: list[float] = []
    height_adjustments: list[float] = []
    for measurement in measurements:
        top_delta = target - measurement.top_from_page_top_mm
        remaining_bottom = measurement.bottom_from_page_bottom_mm - top_delta
        top_spacers.append(top_delta)
        height_adjustments.append(remaining_bottom - target)
    return height_adjustments, top_spacers


def alignment_spreads(
    measurements: list[FrameMeasurement],
    *,
    include_last_bottom: bool = True,
) -> tuple[float, float]:
    tops = [measurement.top_from_page_top_mm for measurement in measurements]
    bottom_measurements = measurements if include_last_bottom else measurements[:-1]
    bottoms = [measurement.bottom_from_page_bottom_mm for measurement in bottom_measurements]
    if not tops:
        raise ValueError("frame measurements are empty")
    bottom_spread = 0.0 if not bottoms else max(bottoms) - min(bottoms)
    return max(tops) - min(tops), bottom_spread


def _report_number(entry: dict[str, Any], key: str, *, index: int) -> float:
    value = entry.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"alignment report pass {index} {key} must be numeric")
    return round(float(value), 3)


def _dark_row_indices(
    samples: bytes,
    *,
    width: int,
    height: int,
    channels: int,
    threshold: int,
    minimum_black: int,
) -> list[int]:
    dark_rows: list[int] = []
    for y in range(height):
        row_start = y * width * channels
        black_pixels = 0
        for x in range(width):
            pixel_start = row_start + x * channels
            if all(samples[pixel_start + channel] <= threshold for channel in range(min(3, channels))):
                black_pixels += 1
        if black_pixels >= minimum_black:
            dark_rows.append(y)
    return dark_rows
