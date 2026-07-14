from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from answercard.ai_layout_to_qspec import ai_layout_to_qspec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert AI layout metadata into a qspec.yaml draft.")
    parser.add_argument("outline_path", type=Path)
    parser.add_argument("ai_layout_path", type=Path)
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--paper-title", required=True)
    parser.add_argument("--omit-front-page", action="store_true")
    args = parser.parse_args(argv)

    try:
        output_path = ai_layout_to_qspec(
            args.outline_path,
            args.ai_layout_path,
            args.output_path,
            paper_title=args.paper_title,
            omit_front_page=args.omit_front_page,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
