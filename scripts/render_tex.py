from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from answercard.render_tex import render_tex


def main() -> None:
    parser = argparse.ArgumentParser(description="Render qspec.yaml to LaTeX.")
    parser.add_argument("spec_path", type=Path)
    parser.add_argument("output_path", type=Path)
    args = parser.parse_args()

    render_tex(args.spec_path, args.output_path)


if __name__ == "__main__":
    main()
