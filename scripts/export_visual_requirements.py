from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from answercard.visual_requirements import export_visual_requirements


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export answer-free visual requirement decisions from validated AI layout JSON."
    )
    parser.add_argument("ai_layout_path", type=Path)
    parser.add_argument("output_path", type=Path)
    args = parser.parse_args(argv)

    try:
        output_path = export_visual_requirements(args.ai_layout_path, args.output_path)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
