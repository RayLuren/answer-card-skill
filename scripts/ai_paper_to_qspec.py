from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from answercard.ai_paper_to_qspec import ai_paper_to_qspec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert ai_paper_spec.json to qspec v2.")
    parser.add_argument("ai_paper_path", type=Path)
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--page-count", type=int, required=True)
    parser.add_argument("--paper-title", required=True)
    parser.add_argument("--omit-front-page", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = ai_paper_to_qspec(
            args.ai_paper_path,
            args.output_path,
            page_count=args.page_count,
            paper_title=args.paper_title,
            omit_front_page=args.omit_front_page,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
