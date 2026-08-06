from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from render_pages import DEFAULT_DPI, RenderPagesError, render_pdf_pages


class RecompileError(RuntimeError):
    """A user-facing failure while recompiling an approved TeX edit."""


def recompile_tex(
    tex_path: str | Path,
    *,
    pages_dir: str | Path | None = None,
    dpi: int = DEFAULT_DPI,
    xelatex: str = "xelatex",
) -> tuple[Path, list[Path]]:
    """Compile an existing TeX file twice, publish atomically, and refresh previews."""

    source = Path(tex_path).resolve()
    if not source.is_file():
        raise RecompileError(f"TeX file not found: {source}")
    if source.suffix.lower() != ".tex":
        raise RecompileError(f"expected a .tex file: {source}")
    if dpi <= 0:
        raise RecompileError("dpi must be greater than 0")

    build_dir = source.parent
    formal_pdf = source.with_suffix(".pdf")
    preview_dir = Path(pages_dir).resolve() if pages_dir is not None else build_dir / "pages"
    log_path = build_dir / "recompile.log"
    pass_logs: list[tuple[int, list[str], str, str]] = []

    with TemporaryDirectory(prefix=".recompile-", dir=build_dir) as staging_name:
        staging_dir = Path(staging_name)
        command = [
            xelatex,
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={staging_dir}",
            source.name,
        ]
        for pass_number in (1, 2):
            try:
                result = subprocess.run(
                    command,
                    cwd=build_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
            except FileNotFoundError as exc:
                raise RecompileError(
                    "xelatex was not found. Install a TeX distribution or add xelatex to PATH."
                ) from exc
            pass_logs.append((pass_number, command, result.stdout, result.stderr))
            if result.returncode != 0:
                _write_recompile_log(log_path, pass_logs)
                raise RecompileError(
                    f"xelatex pass {pass_number} failed with exit code {result.returncode}. "
                    f"See {log_path}."
                )

        staged_pdf = staging_dir / formal_pdf.name
        if not staged_pdf.is_file() or staged_pdf.stat().st_size <= 0:
            _write_recompile_log(log_path, pass_logs)
            raise RecompileError(f"xelatex finished without a usable PDF. See {log_path}.")
        try:
            os.replace(staged_pdf, formal_pdf)
        except PermissionError as exc:
            raise RecompileError(
                f"Cannot replace {formal_pdf}. Close any PDF viewer using it and retry."
            ) from exc

    _write_recompile_log(log_path, pass_logs)
    previews = render_pdf_pages(formal_pdf, preview_dir, dpi=dpi)
    if not previews:
        raise RecompileError(f"preview rendering produced no pages for {formal_pdf}")
    return formal_pdf, previews


def _write_recompile_log(
    path: Path, pass_logs: list[tuple[int, list[str], str, str]]
) -> Path:
    sections: list[str] = []
    for pass_number, command, stdout, stderr in pass_logs:
        sections.extend(
            [
                f"=== pass {pass_number} ===",
                "$ " + " ".join(command),
                "",
                "--- stdout ---",
                stdout,
                "--- stderr ---",
                stderr,
                "",
            ]
        )
    path.write_text("\n".join(sections), encoding="utf-8", newline="\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recompile an approved answer-card TeX edit without rerunning upstream stages."
    )
    parser.add_argument("tex_path", type=Path)
    parser.add_argument("--pages-dir", type=Path, default=None)
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    args = parser.parse_args(argv)

    try:
        pdf_path, previews = recompile_tex(
            args.tex_path,
            pages_dir=args.pages_dir,
            dpi=args.dpi,
        )
    except (OSError, RecompileError, RenderPagesError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(pdf_path)
    print(f"previews: {len(previews)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
