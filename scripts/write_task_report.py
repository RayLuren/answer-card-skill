from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from answercard.task_report import DEFAULT_TASK_REPORT_TITLE, write_task_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate one or more pipeline JSON reports into one task-level Markdown report."
    )
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default=DEFAULT_TASK_REPORT_TITLE)
    args = parser.parse_args(argv)

    try:
        output = write_task_report(args.reports, args.output, title=args.title)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
