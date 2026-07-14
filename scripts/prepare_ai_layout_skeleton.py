from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from answercard.ai_layout_skeleton import write_ai_layout_skeleton


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a no-guess AI-layout JSON skeleton.")
    parser.add_argument("outline", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        written = write_ai_layout_skeleton(args.outline, args.output)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
