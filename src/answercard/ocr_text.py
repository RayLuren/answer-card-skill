"""Transient OCR for image-only reference PDF pages.

Recognized text exists only in memory and must be consumed immediately by the
answer-free outline parser.  This module never writes page images or OCR text.
"""

from __future__ import annotations

from dataclasses import dataclass
import statistics
from pathlib import Path
from typing import Iterable


DEFAULT_OCR_DPI = 220
MIN_OCR_DPI = 150
MAX_OCR_DPI = 600


@dataclass(frozen=True)
class PdfTextLayerProbe:
    page_count: int
    text_pages: frozenset[int]

    @property
    def blank_pages(self) -> frozenset[int]:
        return frozenset(range(1, self.page_count + 1)) - self.text_pages


@dataclass(frozen=True)
class _OcrSpan:
    text: str
    left: float
    top: float
    right: float
    bottom: float

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def height(self) -> float:
        return max(1.0, self.bottom - self.top)


def probe_pdf_text_layers(pdf_path: str | Path) -> PdfTextLayerProbe:
    """Identify pages with extractable text without persisting page content."""

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required for PDF text-layer probing. Install project dependencies first."
        ) from exc

    text_pages: set[int] = set()
    with fitz.open(pdf_path) as document:
        page_count = len(document)
        for page_number, page in enumerate(document, start=1):
            if page.get_text("text").strip():
                text_pages.add(page_number)
    return PdfTextLayerProbe(page_count=page_count, text_pages=frozenset(text_pages))


def extract_ocr_page_texts(
    pdf_path: str | Path,
    page_numbers: Iterable[int],
    *,
    dpi: int = DEFAULT_OCR_DPI,
) -> dict[int, str]:
    """OCR selected one-based PDF pages without persisting source content."""

    if not MIN_OCR_DPI <= dpi <= MAX_OCR_DPI:
        raise ValueError(f"OCR DPI must be between {MIN_OCR_DPI} and {MAX_OCR_DPI}")

    selected_pages = sorted(set(page_numbers))
    if any(page < 1 for page in selected_pages):
        raise ValueError("OCR page numbers must be positive")
    if not selected_pages:
        return {}

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required for transient OCR rendering. Install project dependencies first."
        ) from exc
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            "rapidocr-onnxruntime is required for image-only PDFs. Install project dependencies first."
        ) from exc

    engine = RapidOCR()
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    page_texts: dict[int, str] = {}
    with fitz.open(pdf_path) as document:
        if selected_pages[-1] > len(document):
            raise ValueError("OCR page number exceeds PDF page count")
        for page_number in selected_pages:
            page = document[page_number - 1]
            pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
            result, _elapsed = engine(pixmap.tobytes("png"))
            page_texts[page_number] = "\n".join(_line_texts(_coerce_spans(result)))
    return page_texts


def _normalize_ocr_text(value: str) -> str:
    return (
        value.replace("－", "-")
        .replace("—", "-")
        .replace("–", "-")
        .replace("﹣", "-")
        .strip()
    )


def _coerce_spans(result: object) -> list[_OcrSpan]:
    spans: list[_OcrSpan] = []
    if not isinstance(result, list):
        return spans
    for item in result:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        box, raw_text = item[0], item[1]
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
        except (TypeError, ValueError, IndexError):
            continue
        text = _normalize_ocr_text(str(raw_text))
        if not text:
            continue
        spans.append(
            _OcrSpan(
                text=text,
                left=min(xs),
                top=min(ys),
                right=max(xs),
                bottom=max(ys),
            )
        )
    return spans


def _line_texts(spans: Iterable[_OcrSpan]) -> list[str]:
    ordered = sorted(spans, key=lambda span: (span.center_y, span.left))
    lines: list[list[_OcrSpan]] = []
    for span in ordered:
        best_line: list[_OcrSpan] | None = None
        best_distance: float | None = None
        for line in lines:
            line_center = statistics.median(part.center_y for part in line)
            line_height = statistics.median(part.height for part in line)
            distance = abs(span.center_y - line_center)
            if distance <= max(6.0, min(span.height, line_height) * 0.55):
                if best_distance is None or distance < best_distance:
                    best_line = line
                    best_distance = distance
        if best_line is None:
            lines.append([span])
        else:
            best_line.append(span)

    lines.sort(key=lambda line: statistics.median(span.center_y for span in line))
    return [" ".join(span.text for span in sorted(line, key=lambda part: part.left)) for line in lines]
