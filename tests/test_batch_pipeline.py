from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

import answercard.batch as batch_contract


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "batch_pipeline.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("batch_pipeline_script", SCRIPT_PATH)
assert SCRIPT_SPEC is not None
batch_pipeline = importlib.util.module_from_spec(SCRIPT_SPEC)
assert SCRIPT_SPEC.loader is not None
sys.modules[SCRIPT_SPEC.name] = batch_pipeline
SCRIPT_SPEC.loader.exec_module(batch_pipeline)


def _valid_layout() -> dict:
    return {
        "questions": [
            {
                "id": "1",
                "score": 10,
                "percent": 100,
                "percent_source": "printed",
                "items": [
                    {
                        "id": "1-1",
                        "kind": "short_answer",
                        "height": "24mm",
                        "fallback_after_reinspection": False,
                        "visual_requirement": "no_visual",
                        "visual_type": "none",
                    }
                ],
            }
        ]
    }


def _prepare(tmp_path: Path, monkeypatch, *, count: int = 1) -> Path:
    source = tmp_path / "inputs"
    source.mkdir()
    for index in range(count):
        (source / f"任意文件-{index}.pdf").write_bytes(f"%PDF-{index}".encode())

    monkeypatch.setattr(batch_contract, "_project_temp_root", lambda: tmp_path / "temp")
    monkeypatch.setattr(batch_pipeline, "TEMP_ROOT", tmp_path / "temp")
    prompt = tmp_path / "project" / "prompts" / "ai_layout_judge.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("fixed", encoding="utf-8")
    monkeypatch.setattr(batch_pipeline, "PROMPT_PATH", prompt)

    def fake_extract(pdf_path: Path, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {
                    "source": str(pdf_path),
                    "questions": [
                        {
                            "id": "1",
                            "title": "第一题",
                            "score": 10,
                            "page": 1,
                            "items": [{"id": "1-1", "page": 1}],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return output_path

    def fake_render(pdf_path: Path, output_dir: Path, *, dpi: int) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        page = output_dir / "page-001.png"
        page.write_bytes(b"png")
        return [page]

    monkeypatch.setattr(batch_pipeline, "extract_outline", fake_extract)
    monkeypatch.setattr(batch_pipeline, "render_pdf_pages", fake_render)
    return batch_pipeline.prepare_batch(source, tmp_path / "outputs", visual_workers=2)


def _state(manifest_path: Path) -> dict:
    manifest = batch_contract.load_batch_manifest(manifest_path)
    return batch_contract.load_batch_state(Path(manifest["run_dir"]) / "batch_state.json", manifest)


def test_prepare_writes_strict_jobs_and_awaiting_state(tmp_path: Path, monkeypatch) -> None:
    manifest_path = _prepare(tmp_path, monkeypatch, count=2)
    manifest = batch_contract.load_batch_manifest(manifest_path)
    state = _state(manifest_path)
    assert manifest["concurrency"]["visual_workers"] == 2
    assert [item["status"] for item in state["papers"].values()] == [
        "awaiting_ai_layout",
        "awaiting_ai_layout",
    ]
    for paper in manifest["papers"]:
        job = json.loads(Path(state["papers"][paper["id"]]["job_path"]).read_text(encoding="utf-8"))
        assert job["attempt"] == 1
        assert job["allowed_output_path"].endswith("ai_layout.attempt-1.json")
        assert not list(Path(paper["evidence_dir"]).rglob("contact-*.png"))


def test_first_invalid_attempt_gets_fresh_retry_then_success(tmp_path: Path, monkeypatch) -> None:
    manifest_path = _prepare(tmp_path, monkeypatch)
    state = _state(manifest_path)
    first = Path(json.loads(Path(state["papers"]["paper001"]["job_path"]).read_text())["allowed_output_path"])
    first.write_text("not-json", encoding="utf-8")

    result = batch_pipeline.accept_ai_layout(manifest_path, "paper001", first)
    assert result["papers"]["paper001"]["status"] == "awaiting_ai_layout"
    assert result["papers"]["paper001"]["attempt"] == 2
    assert not first.exists()

    state = _state(manifest_path)
    second_job = json.loads(Path(state["papers"]["paper001"]["job_path"]).read_text())
    second = Path(second_job["allowed_output_path"])
    second.write_text(json.dumps(_valid_layout()), encoding="utf-8")
    result = batch_pipeline.accept_ai_layout(manifest_path, "paper001", second)
    assert result["papers"]["paper001"]["status"] == "ai_layout_valid"
    assert (second.parent / "ai_layout.json").is_file()
    history = _state(manifest_path)["papers"]["paper001"]["history"]
    assert [entry["status"] for entry in history].count("ai_layout_running") == 2


def test_two_invalid_attempts_fail_and_remove_untrusted_output(tmp_path: Path, monkeypatch) -> None:
    manifest_path = _prepare(tmp_path, monkeypatch)
    for attempt in (1, 2):
        state = _state(manifest_path)
        job = json.loads(Path(state["papers"]["paper001"]["job_path"]).read_text())
        output = Path(job["allowed_output_path"])
        output.write_text('{"visual_description":"sensitive page content"}', encoding="utf-8")
        result = batch_pipeline.accept_ai_layout(manifest_path, "paper001", output)
    assert result["papers"]["paper001"]["status"] == "failed"
    assert result["papers"]["paper001"]["error"]["code"] == "AI_RETRY_EXHAUSTED"
    assert not output.exists()
    manifest = batch_contract.load_batch_manifest(manifest_path)
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in Path(manifest["run_dir"]).rglob("*.json")
    )
    assert "sensitive page content" not in persisted
    assert not Path(manifest["papers"][0]["evidence_dir"]).exists()


def test_structural_conflict_fails_without_retry(tmp_path: Path, monkeypatch) -> None:
    manifest_path = _prepare(tmp_path, monkeypatch)
    state = _state(manifest_path)
    job = json.loads(Path(state["papers"]["paper001"]["job_path"]).read_text())
    output = Path(job["allowed_output_path"])
    layout = _valid_layout()
    layout["questions"][0]["score"] = 11
    output.write_text(json.dumps(layout), encoding="utf-8")
    result = batch_pipeline.accept_ai_layout(manifest_path, "paper001", output)
    assert result["papers"]["paper001"]["status"] == "failed"
    assert result["papers"]["paper001"]["attempt"] == 1
    assert result["papers"]["paper001"]["error"]["code"] == "AI_LAYOUT_CONFLICT"


def test_build_only_accepted_paper_publishes_root_and_archives_audit(
    tmp_path: Path, monkeypatch
) -> None:
    manifest_path = _prepare(tmp_path, monkeypatch, count=2)
    state = _state(manifest_path)
    job = json.loads(Path(state["papers"]["paper001"]["job_path"]).read_text())
    output = Path(job["allowed_output_path"])
    output.write_text(json.dumps(_valid_layout()), encoding="utf-8")
    batch_pipeline.accept_ai_layout(manifest_path, "paper001", output)

    calls: list[tuple[str, bool]] = []

    def fake_pipeline(pdf_path: Path, **kwargs):
        calls.append((Path(pdf_path).name, kwargs["use_existing_outline"]))
        build_dir = Path(kwargs["build_dir"])
        (build_dir / "answercard.pdf").write_bytes(b"final-pdf")
        return object()

    monkeypatch.setattr(batch_pipeline, "run_full_pipeline", fake_pipeline)
    monkeypatch.setattr(batch_pipeline, "finalize_pipeline", lambda **kwargs: {"status": "passed"})
    result = batch_pipeline.build_papers(manifest_path)
    manifest = batch_contract.load_batch_manifest(manifest_path)
    first = manifest["papers"][0]
    second = manifest["papers"][1]
    assert calls == [(first["source"]["filename"], True)]
    assert result["papers"]["paper001"]["status"] == "validated"
    assert result["papers"]["paper002"]["status"] == "awaiting_ai_layout"
    assert (Path(manifest["run_dir"]) / first["output_name"]).read_bytes() == b"final-pdf"
    assert Path(first["audit_dir"]).is_dir()
    assert not (Path(first["audit_dir"]) / "answercard.pdf").exists()
    assert Path(second["workspace"]).is_dir()
    batch_pipeline.build_papers(manifest_path)
    assert len(calls) == 1


def test_partial_failure_does_not_block_single_report_and_report_is_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    manifest_path = _prepare(tmp_path, monkeypatch, count=2)
    batch_pipeline.fail_paper(manifest_path, "paper001", "CAPABILITY_UNAVAILABLE")
    batch_pipeline.fail_paper(manifest_path, "paper002", "USER_ABORTED")
    manifest = batch_contract.load_batch_manifest(manifest_path)
    run_dir = Path(manifest["run_dir"])

    calls = 0

    def fake_task_report(paths, destination):
        nonlocal calls
        calls += 1
        Path(destination).write_text("# report\n", encoding="utf-8")
        return Path(destination)

    monkeypatch.setattr(batch_pipeline, "write_task_report", fake_task_report)
    first = batch_pipeline.write_batch_report(manifest_path)
    first_mtime = first.stat().st_mtime_ns
    second = batch_pipeline.write_batch_report(manifest_path)
    run_report = json.loads((run_dir / "run-report.json").read_text(encoding="utf-8"))
    assert first == second
    assert first.stat().st_mtime_ns == first_mtime
    assert calls == 1
    assert run_report["input_count"] == 2
    assert run_report["failure_count"] == 2
    assert {paper["id"] for paper in run_report["papers"]} == {"paper001", "paper002"}
    assert not (Path(batch_pipeline.TEMP_ROOT) / "batches" / manifest["batch_id"]).exists()


def test_build_failure_archives_diagnostics_but_scrubs_exception_text(
    tmp_path: Path, monkeypatch
) -> None:
    manifest_path = _prepare(tmp_path, monkeypatch)
    state = _state(manifest_path)
    job = json.loads(Path(state["papers"]["paper001"]["job_path"]).read_text())
    output = Path(job["allowed_output_path"])
    output.write_text(json.dumps(_valid_layout()), encoding="utf-8")
    batch_pipeline.accept_ai_layout(manifest_path, "paper001", output)

    def fail_pipeline(*args, **kwargs):
        report = Path(kwargs["report_path"])
        data = json.loads(report.read_text(encoding="utf-8"))
        data["stages"].append(
            {
                "id": "999",
                "name": "build_answer_card",
                "source": "script",
                "status": "failed",
                "error": "sensitive visual description",
            }
        )
        report.write_text(json.dumps(data), encoding="utf-8")
        raise RuntimeError("sensitive visual description")

    monkeypatch.setattr(batch_pipeline, "run_full_pipeline", fail_pipeline)
    result = batch_pipeline.build_papers(manifest_path)
    manifest = batch_contract.load_batch_manifest(manifest_path)
    failed_dir = Path(manifest["papers"][0]["failed_dir"])
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore") for path in failed_dir.rglob("*.json")
    )
    assert result["papers"]["paper001"]["error"]["code"] == "BUILD_FAILED"
    assert "sensitive visual description" not in persisted
    assert not Path(manifest["papers"][0]["evidence_dir"]).exists()


def test_one_build_failure_does_not_block_another_accepted_paper(
    tmp_path: Path, monkeypatch
) -> None:
    manifest_path = _prepare(tmp_path, monkeypatch, count=2)
    for paper_id in ("paper001", "paper002"):
        state = _state(manifest_path)
        job = json.loads(Path(state["papers"][paper_id]["job_path"]).read_text())
        output = Path(job["allowed_output_path"])
        output.write_text(json.dumps(_valid_layout()), encoding="utf-8")
        batch_pipeline.accept_ai_layout(manifest_path, paper_id, output)

    calls = 0

    def mixed_pipeline(pdf_path: Path, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("first build failed")
        (Path(kwargs["build_dir"]) / "answercard.pdf").write_bytes(b"second-pdf")
        return object()

    monkeypatch.setattr(batch_pipeline, "run_full_pipeline", mixed_pipeline)
    monkeypatch.setattr(batch_pipeline, "finalize_pipeline", lambda **kwargs: {"status": "passed"})
    result = batch_pipeline.build_papers(manifest_path)
    assert result["papers"]["paper001"]["status"] == "failed"
    assert result["papers"]["paper002"]["status"] == "validated"
    assert calls == 2


def test_report_rejects_nonterminal_batch(tmp_path: Path, monkeypatch) -> None:
    manifest_path = _prepare(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="validated or failed"):
        batch_pipeline.write_batch_report(manifest_path)


def test_status_detects_source_change_as_terminal_failure(tmp_path: Path, monkeypatch) -> None:
    manifest_path = _prepare(tmp_path, monkeypatch)
    manifest = batch_contract.load_batch_manifest(manifest_path)
    Path(manifest["papers"][0]["source"]["path"]).write_bytes(b"changed")
    result = batch_pipeline.batch_status(manifest_path)
    assert result["papers"]["paper001"]["status"] == "failed"
    assert result["papers"]["paper001"]["error"]["code"] == "SOURCE_CHANGED"
