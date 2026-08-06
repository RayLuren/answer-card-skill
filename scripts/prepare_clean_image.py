from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from answercard.clean_image import (  # noqa: E402
    DEFAULT_THRESHOLD,
    CleanImageError,
    prepare_clean_image,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a deterministic sibling <name>-clean.png without modifying the source image."
    )
    parser.add_argument("source_image", type=Path)
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)

    try:
        result = prepare_clean_image(args.source_image, threshold=args.threshold)
    except CleanImageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    state = "created" if result.created else "unchanged"
    print(f"status: {state}")
    print(f"path: {result.output_path}")
    print(f"sha256: {result.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
