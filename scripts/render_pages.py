from __future__ import annotations

import argparse
from pathlib import Path
import sys


DEFAULT_DPI = 150


class RenderPagesError(RuntimeError):
    """A user-facing PDF preview rendering failure."""


def page_png_path(output_dir: str | Path, page_number: int) -> Path:
    """Return the stable PNG path for a 1-based PDF page number."""

    if page_number < 1:
        raise ValueError("page_number must be 1 or greater")
    return Path(output_dir) / f"page-{page_number:03d}.png"


def render_pdf_pages(pdf_path: str | Path, output_dir: str | Path, *, dpi: int = DEFAULT_DPI) -> list[Path]:
    """Render each PDF page to a PNG preview image and return the created paths."""

    source = Path(pdf_path)
    destination = Path(output_dir)

    if not source.exists():
        raise RenderPagesError(f"PDF not found: {source}")
    if dpi <= 0:
        raise ValueError("dpi must be greater than 0")

    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RenderPagesError(
            "PyMuPDF is required to render PDF previews. Install it with "
            "`python -m pip install pymupdf`, then rerun this command."
        ) from exc

    destination.mkdir(parents=True, exist_ok=True)
    _remove_stale_page_previews(destination)
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    rendered_paths: list[Path] = []

    try:
        with fitz.open(source) as document:
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                output_path = page_png_path(destination, page_index + 1)
                pixmap.save(output_path)
                rendered_paths.append(output_path)
    except Exception as exc:
        raise RenderPagesError(f"Failed to render {source}: {exc}") from exc

    return rendered_paths


def _remove_stale_page_previews(output_dir: Path) -> None:
    for stale_preview in output_dir.glob("page-*.png"):
        stale_preview.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render each PDF page to PNG preview images.")
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    args = parser.parse_args(argv)

    try:
        rendered_paths = render_pdf_pages(args.pdf_path, args.output_dir, dpi=args.dpi)
    except (RenderPagesError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for path in rendered_paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
