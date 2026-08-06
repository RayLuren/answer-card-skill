from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from answercard.pipeline_timing import PipelineTimer


DEFAULT_REPORT_PATH = PROJECT_ROOT / "build" / "pipeline_report.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record and summarize answer-card pipeline wall-clock stages.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)

    begin_parser = subparsers.add_parser("begin")
    begin_parser.add_argument("--label", default=None)

    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("stage")
    start_parser.add_argument("--source", choices=("agent", "script", "manual"), default="agent")

    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument("stage")
    stop_parser.add_argument("--status", choices=("passed", "failed"), default="passed")
    stop_parser.add_argument("--code", default=None)

    finish_parser = subparsers.add_parser("finish")
    finish_parser.add_argument("--status", choices=("passed", "failed"), default="passed")

    subparsers.add_parser("summary")
    args = parser.parse_args(argv)

    try:
        timer = PipelineTimer(args.report)
        if args.command == "begin":
            timer.begin(label=args.label, reset=True)
            print(f"timer started: {args.report}")
        elif args.command == "start":
            stage_id = timer.start_stage(args.stage, source=args.source)
            print(f"stage started: {stage_id} {args.stage}")
        elif args.command == "stop":
            if args.status == "failed":
                if not args.code:
                    raise ValueError("failed stage stop requires --code")
                if re.fullmatch(r"[A-Z][A-Z0-9_]*", args.code) is None:
                    raise ValueError("failure code must use uppercase letters, digits, and underscores")
            elif args.code is not None:
                raise ValueError("passed stage stop must not include --code")
            stage = timer.stop_stage(args.stage, status=args.status, error=args.code)
            print(f"stage stopped: {stage['id']} {stage['name']} {stage['duration_seconds']:.3f}s")
        elif args.command == "finish":
            timer.finish(status=args.status)
            print(timer.summary_text())
        else:
            print(timer.summary_text())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
