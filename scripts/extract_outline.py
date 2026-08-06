from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from answercard.extract_outline import extract_outline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract reference-answer PDF structure to outline.json.")
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--no-ocr", action="store_true", help="Disable OCR fallback for pages without text.")
    parser.add_argument("--ocr-dpi", type=int, default=220)
    args = parser.parse_args(argv)

    try:
        output_path = extract_outline(
            args.pdf_path,
            args.output_path,
            ocr_fallback=not args.no_ocr,
            ocr_dpi=args.ocr_dpi,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
