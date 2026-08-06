from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "recompile_tex.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("answercard_recompile_tex_script", SCRIPT_PATH)
assert SCRIPT_SPEC is not None
recompile_script = importlib.util.module_from_spec(SCRIPT_SPEC)
assert SCRIPT_SPEC.loader is not None
SCRIPT_SPEC.loader.exec_module(recompile_script)


def test_recompile_tex_runs_from_tex_directory_and_publishes_after_two_passes(
    tmp_path: Path, monkeypatch
) -> None:
    tex_path = tmp_path / "answercard.tex"
    tex_path.write_text("approved edit", encoding="utf-8")
    formal_pdf = tmp_path / "answercard.pdf"
    formal_pdf.write_bytes(b"old-pdf")
    calls: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, Path(kwargs["cwd"])))
        output_argument = next(item for item in command if item.startswith("-output-directory="))
        output_dir = Path(output_argument.split("=", 1)[1])
        output_dir.joinpath("answercard.pdf").write_bytes(f"pass-{len(calls)}".encode())
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    def fake_render(pdf_path: Path, output_dir: Path, *, dpi: int) -> list[Path]:
        assert pdf_path.read_bytes() == b"pass-2"
        assert dpi == 150
        output_dir.mkdir(parents=True, exist_ok=True)
        preview = output_dir / "page-001.png"
        preview.write_bytes(b"png")
        return [preview]

    monkeypatch.setattr(recompile_script.subprocess, "run", fake_run)
    monkeypatch.setattr(recompile_script, "render_pdf_pages", fake_render)

    pdf_path, previews = recompile_script.recompile_tex(tex_path)

    assert pdf_path == formal_pdf
    assert formal_pdf.read_bytes() == b"pass-2"
    assert len(calls) == 2
    assert all(cwd == tmp_path for _command, cwd in calls)
    assert previews == [tmp_path / "pages" / "page-001.png"]
    assert "=== pass 2 ===" in (tmp_path / "recompile.log").read_text(encoding="utf-8")


def test_recompile_tex_keeps_formal_pdf_when_second_pass_fails(
    tmp_path: Path, monkeypatch
) -> None:
    tex_path = tmp_path / "answercard.tex"
    tex_path.write_text("approved edit", encoding="utf-8")
    formal_pdf = tmp_path / "answercard.pdf"
    formal_pdf.write_bytes(b"old-pdf")
    calls = 0

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            output_argument = next(item for item in command if item.startswith("-output-directory="))
            output_dir = Path(output_argument.split("=", 1)[1])
            output_dir.joinpath("answercard.pdf").write_bytes(b"first-pass")
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")
        return subprocess.CompletedProcess(command, 1, stdout="failed", stderr="fatal")

    monkeypatch.setattr(recompile_script.subprocess, "run", fake_run)

    with pytest.raises(recompile_script.RecompileError, match="pass 2 failed"):
        recompile_script.recompile_tex(tex_path)

    assert formal_pdf.read_bytes() == b"old-pdf"
    log = (tmp_path / "recompile.log").read_text(encoding="utf-8")
    assert "failed" in log
    assert "fatal" in log
