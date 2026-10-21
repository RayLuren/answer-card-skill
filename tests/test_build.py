from pathlib import Path
import importlib.util
import subprocess
from unittest.mock import Mock

import pytest

from answercard.frame_alignment import FrameMeasurement


BUILD_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build.py"
BUILD_SPEC = importlib.util.spec_from_file_location("answercard_build_script", BUILD_SCRIPT_PATH)
assert BUILD_SPEC is not None
build_script = importlib.util.module_from_spec(BUILD_SPEC)
assert BUILD_SPEC.loader is not None
BUILD_SPEC.loader.exec_module(build_script)

BuildError = build_script.BuildError
build_answer_card = build_script.build_answer_card


def test_build_invokes_xelatex_with_expected_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build_dir = tmp_path / "build"

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        build_dir.joinpath("answercard.pdf").write_bytes(b"%PDF-1.7\n")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    run = Mock(side_effect=fake_run)
    monkeypatch.setattr(subprocess, "run", run)

    pdf_path = build_answer_card("spec/qspec.sample.yaml", build_dir=build_dir)

    assert pdf_path == build_dir / "answercard.pdf"
    assert build_dir.joinpath("answercard.tex").exists()
    run.assert_called_once_with(
        ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "answercard.tex"],
        cwd=build_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_successful_build_replaces_the_previous_failed_compile_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    log_path = build_dir / "build.log"
    log_path.write_text("previous failed compilation", encoding="utf-8")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        (build_dir / "answercard.pdf").write_bytes(b"%PDF-1.7\n")
        return subprocess.CompletedProcess(command, 0, stdout="current successful compilation", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    build_answer_card("spec/qspec.sample.yaml", build_dir=build_dir)

    log = log_path.read_text(encoding="utf-8")
    assert "current successful compilation" in log
    assert "previous failed compilation" not in log


def test_build_rejects_missing_glyphs_even_when_xelatex_reports_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_dir = tmp_path / "build"
    message = "Missing character: A required character is absent from the selected font."

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        (build_dir / "answercard.pdf").write_bytes(b"%PDF-1.7\n")
        return subprocess.CompletedProcess(command, 0, stdout=message, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(BuildError, match="font is missing glyphs"):
        build_answer_card("spec/qspec.sample.yaml", build_dir=build_dir)

    assert not (build_dir / "answercard.pdf").exists()
    assert message in (build_dir / "build.log").read_text(encoding="utf-8")


def test_build_reports_missing_xelatex_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(BuildError, match="xelatex was not found"):
        build_answer_card("spec/qspec.sample.yaml", build_dir=tmp_path / "build")


def test_build_writes_log_when_xelatex_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, 1, stdout="tex stdout", stderr="tex stderr")

    monkeypatch.setattr(subprocess, "run", fake_run)
    build_dir = tmp_path / "build"

    with pytest.raises(BuildError, match="See .*build.log"):
        build_answer_card("spec/qspec.sample.yaml", build_dir=build_dir)

    log = build_dir.joinpath("build.log").read_text(encoding="utf-8")
    assert "$ xelatex -interaction=nonstopmode -halt-on-error answercard.tex" in log
    assert "tex stdout" in log
    assert "tex stderr" in log


def test_build_rejects_stale_pdf_when_xelatex_returns_success_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    stale_pdf = build_dir / "answercard.pdf"
    stale_pdf.write_bytes(b"%PDF-stale\n")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        assert not stale_pdf.exists()
        return subprocess.CompletedProcess(command, 0, stdout="driver failed", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(BuildError, match="without a usable new PDF"):
        build_answer_card("spec/qspec.sample.yaml", build_dir=build_dir)

    assert not stale_pdf.exists()
    assert "driver failed" in build_dir.joinpath("build.log").read_text(encoding="utf-8")


def test_alignment_skips_the_integrated_front_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = tmp_path / "qspec.yaml"
    spec_path.write_text(
        """
schema_version: 1
paper:
  title: Chemistry Answer Card
  page_size: A4
  omit_front_page: false
  total_score: 10
  margin: {top: 12mm, bottom: 12mm, left: 10mm, right: 10mm}
style: {label_width: 13mm, border_width: 0.6pt, box_gap: 1.5mm, title_gap: 2mm}
questions:
  - id: "1"
    title: Question
    score: 10
    percent: 100
    blocks: [{id: "1-1", kind: short_answer, height: 24mm}]
""",
        encoding="utf-8",
    )
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    tex_path = build_dir / "answercard.tex"
    pdf_path = build_dir / "answercard.pdf"
    calls: list[tuple[Path, int]] = []

    def fake_measure(path: Path, *, skip_pages: int) -> list[FrameMeasurement]:
        calls.append((path, skip_pages))
        return [
            FrameMeasurement(
                page=2,
                top_from_page_top_mm=12.0,
                bottom_from_page_bottom_mm=12.0,
            )
        ]

    monkeypatch.setattr(build_script, "measure_pdf_frames", fake_measure)

    build_script._align_compiled_pages(
        spec_path,
        tex_path,
        pdf_path,
        build_dir,
        xelatex="xelatex",
        max_passes=1,
        tolerance_mm=0.7,
    )

    assert calls == [(pdf_path, 1)]
    report = build_dir.joinpath("frame_alignment.json").read_text(encoding="utf-8")
    assert '"page": 2' in report


def test_alignment_accepts_a_bounded_repagination_after_height_growth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = tmp_path / "qspec.yaml"
    spec_path.write_text(
        """
schema_version: 1
paper:
  title: Repagination Test
  page_size: A4
  omit_front_page: true
  total_score: 30
  margin: {top: 12mm, bottom: 12mm, left: 10mm, right: 10mm}
style: {label_width: 13mm, border_width: 0.6pt, box_gap: 1.5mm, title_gap: 2mm}
questions:
  - id: "1"
    title: One
    score: 10
    percent: 34
    blocks:
      - {id: "1-1", kind: calculation, height: 130mm}
      - {id: "1-2", kind: calculation, height: 130mm}
      - {id: "1-3", kind: short_answer, height: 4mm}
  - id: "2"
    title: Two
    score: 10
    percent: 33
    blocks:
      - {id: "2-1", kind: calculation, height: 130mm, force_page_break_before: true}
      - {id: "2-2", kind: calculation, height: 130mm}
  - id: "3"
    title: Three
    score: 10
    percent: 33
    blocks:
      - {id: "3-1", kind: short_answer, height: 20mm, force_page_break_before: true}
""",
        encoding="utf-8",
    )
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    tex_path = build_dir / "answercard.tex"
    pdf_path = build_dir / "answercard.pdf"
    measurement_counts: list[int] = []

    def fake_measure(path: Path, *, skip_pages: int) -> list[FrameMeasurement]:
        assert path == pdf_path
        assert skip_pages == 0
        if not measurement_counts:
            result = [
                FrameMeasurement(page=1, top_from_page_top_mm=16.0, bottom_from_page_bottom_mm=19.0),
                FrameMeasurement(page=2, top_from_page_top_mm=16.0, bottom_from_page_bottom_mm=16.0),
                FrameMeasurement(page=3, top_from_page_top_mm=16.0, bottom_from_page_bottom_mm=60.0),
            ]
        else:
            result = [
                FrameMeasurement(page=index, top_from_page_top_mm=16.0, bottom_from_page_bottom_mm=16.0)
                for index in range(1, 5)
            ]
        measurement_counts.append(len(result))
        return result

    compile_mock = Mock()
    monkeypatch.setattr(build_script, "measure_pdf_frames", fake_measure)
    monkeypatch.setattr(build_script, "_compile_tex", compile_mock)

    build_script._align_compiled_pages(
        spec_path,
        tex_path,
        pdf_path,
        build_dir,
        xelatex="xelatex",
        max_passes=2,
        tolerance_mm=1.1,
    )

    assert measurement_counts == [3, 4]
    compile_mock.assert_called_once()
    tex = tex_path.read_text(encoding="utf-8")
    assert tex.count(r"\par\newpage") == 3




def test_alignment_recovers_unexpected_tex_page_growth_without_changing_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_path = tmp_path / "qspec.yaml"
    spec_path.write_text("""
schema_version: 1
paper:
  title: Measured page recovery
  page_size: A4
  omit_front_page: true
  total_score: 30
  margin: {top: 12mm, bottom: 12mm, left: 10mm, right: 10mm}
style: {label_width: 13mm, border_width: 0.6pt, box_gap: 1.5mm, title_gap: 2mm}
questions:
  - id: "1"
    title: One
    score: 10
    percent: 34
    blocks: [{id: "1-1", kind: calculation, height: 60mm}]
  - id: "2"
    title: Two
    score: 10
    percent: 33
    blocks: [{id: "2-1", kind: calculation, height: 60mm, force_page_break_before: true}]
  - id: "3"
    title: Three
    score: 10
    percent: 33
    blocks: [{id: "3-1", kind: calculation, height: 60mm, force_page_break_before: true}]
""", encoding="utf-8")
    original = spec_path.read_bytes()
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    batches = [
        [FrameMeasurement(1,16,16), FrameMeasurement(2,12,20), FrameMeasurement(3,16,50)],
        [FrameMeasurement(i,12,40+i*10) for i in range(1,5)],
        [FrameMeasurement(1,16,16), FrameMeasurement(2,16,16), FrameMeasurement(3,16,50)],
    ]
    measure = Mock(side_effect=batches)
    compile_mock = Mock()
    monkeypatch.setattr(build_script, "measure_pdf_frames", measure)
    monkeypatch.setattr(build_script, "_compile_tex", compile_mock)
    build_script._align_compiled_pages(
        spec_path, build_dir/"answercard.tex", build_dir/"answercard.pdf", build_dir,
        xelatex="xelatex", max_passes=3, tolerance_mm=1.1,
    )
    assert compile_mock.call_count == 2
    assert measure.call_count == 3
    assert spec_path.read_bytes() == original
    import json
    passes=json.loads((build_dir/"frame_alignment.json").read_text(encoding="utf-8"))["passes"]
    assert [(p["expected_body_pages"], p["measured_body_pages"]) for p in passes] == [(3,3),(3,4),(3,3)]
    assert (build_dir/"answercard.tex").read_text(encoding="utf-8").count(r"\par\newpage") == 2


def test_build_cli_forwards_an_isolated_build_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    isolated_build = tmp_path / "isolated-build"
    expected_pdf = isolated_build / "answercard.pdf"
    calls: list[tuple[Path, Path, bool]] = []

    def fake_build(
        spec_path: Path,
        *,
        build_dir: Path,
        align_pages: bool,
    ) -> Path:
        calls.append((spec_path, build_dir, align_pages))
        return expected_pdf

    monkeypatch.setattr(build_script, "build_answer_card", fake_build)

    exit_code = build_script.main(
        [
            "spec/qspec.sample.yaml",
            "--build-dir",
            str(isolated_build),
            "--align-pages",
        ]
    )

    assert exit_code == 0
    assert calls == [(Path("spec/qspec.sample.yaml"), isolated_build, True)]
    assert capsys.readouterr().out.strip() == str(expected_pdf)
