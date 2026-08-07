from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from answercard.batch import default_paper_title, load_batch_manifest, load_batch_state
from scripts import batch_pipeline
from test_ai_paper_schema import ready_spec, review_spec


def _pdf(path: Path) -> None:
    document = fitz.open()
    document.new_page()
    document.new_page()
    document.save(path)
    document.close()


def test_default_title_removes_answer_and_scoring_suffixes() -> None:
    assert default_paper_title("第27届国初 答案及评分标准") == "第27届国初答题卡"
    assert default_paper_title("第38届国初 答案与评分细则") == "第38届国初答题卡"
    assert default_paper_title("第36届国初（一卷）评分标准") == "第36届国初（一卷）答题卡"


def test_prepare_renders_only_pages_and_job_has_no_outline_or_ocr(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    _pdf(source / "paper.pdf")
    manifest_path = batch_pipeline.prepare_batch(source, output)
    manifest = load_batch_manifest(manifest_path)
    state = load_batch_state(Path(manifest["run_dir"]) / "batch_state.json", manifest)
    current = state["papers"]["paper001"]
    job = json.loads(Path(current["job_path"]).read_text(encoding="utf-8"))
    assert current["status"] == "awaiting_ai_paper"
    assert job["schema_version"] == 2
    assert job["revision"] == 0
    assert job["human_confirmation_path"] is None
    assert "outline_path" not in job and "skeleton_path" not in job and "ocr" not in json.dumps(job).lower()
    assert Path(job["source_pages_dir"], "page-001.png").is_file()


def test_human_review_creates_immutable_revision_and_fresh_job(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    _pdf(source / "paper.pdf")
    manifest_path = batch_pipeline.prepare_batch(source, output)
    status = batch_pipeline.batch_status(manifest_path)
    job_path = Path(status["papers"]["paper001"]["job_path"])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    attempt = Path(job["allowed_output_path"])
    attempt.write_text(json.dumps(review_spec(), ensure_ascii=False), encoding="utf-8")
    status = batch_pipeline.accept_ai_paper(manifest_path, "paper001", attempt)
    assert status["papers"]["paper001"]["status"] == "awaiting_human_confirmation"
    assert status["papers"]["paper001"]["revision"] == 1
    confirmation = tmp_path / "confirmation.json"
    confirmation.write_text(
        json.dumps({"schema_version": 1, "paper_id": "paper001", "revision": 1, "decisions": [{"review_id": "r001", "value": "7"}]}),
        encoding="utf-8",
    )
    status = batch_pipeline.confirm_ai_paper(manifest_path, "paper001", confirmation)
    current = status["papers"]["paper001"]
    assert current["status"] == "awaiting_ai_paper"
    assert current["attempt"] == 1 and current["revision"] == 1
    assert Path(current["confirmation_path"]).name == "human_confirmation.revision-1.json"
    next_job = json.loads(Path(current["job_path"]).read_text(encoding="utf-8"))
    assert next_job["human_confirmation_path"] == current["confirmation_path"]
    assert "ai_paper_spec.revision-1.attempt-1.json" in next_job["allowed_output_path"]


def test_ready_result_is_promoted_without_numbering_audit(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    _pdf(source / "paper.pdf")
    manifest_path = batch_pipeline.prepare_batch(source, output)
    status = batch_pipeline.batch_status(manifest_path)
    job = json.loads(Path(status["papers"]["paper001"]["job_path"]).read_text(encoding="utf-8"))
    attempt = Path(job["allowed_output_path"])
    attempt.write_text(json.dumps(ready_spec(), ensure_ascii=False), encoding="utf-8")
    status = batch_pipeline.accept_ai_paper(manifest_path, "paper001", attempt)
    assert status["papers"]["paper001"]["status"] == "ai_paper_valid"
    assert Path(attempt.parent, "ai_paper_spec.json").is_file()


def test_invalid_attempt_is_removed_and_creates_one_fresh_retry(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    _pdf(source / "paper.pdf")
    manifest_path = batch_pipeline.prepare_batch(source, output)
    status = batch_pipeline.batch_status(manifest_path)
    job = json.loads(Path(status["papers"]["paper001"]["job_path"]).read_text(encoding="utf-8"))
    attempt = Path(job["allowed_output_path"])
    attempt.write_text("not json", encoding="utf-8")
    status = batch_pipeline.accept_ai_paper(manifest_path, "paper001", attempt)
    current = status["papers"]["paper001"]
    assert not attempt.exists()
    assert current["status"] == "awaiting_ai_paper"
    assert current["attempt"] == 2 and current["revision"] == 0
    retry_job = json.loads(Path(current["job_path"]).read_text(encoding="utf-8"))
    assert retry_job["attempt"] == 2
    assert "outline_path" not in retry_job and "skeleton_path" not in retry_job


def test_formal_report_waits_for_all_terminal_papers(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    _pdf(source / "paper.pdf")
    manifest_path = batch_pipeline.prepare_batch(source, output)
    with pytest.raises(ValueError, match="requires every paper"):
        batch_pipeline.write_batch_report(manifest_path)


def test_batch_build_forwards_explicit_alignment_pass_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    _pdf(source / "paper.pdf")
    manifest_path = batch_pipeline.prepare_batch(source, output)
    status = batch_pipeline.batch_status(manifest_path)
    job = json.loads(Path(status["papers"]["paper001"]["job_path"]).read_text(encoding="utf-8"))
    attempt = Path(job["allowed_output_path"])
    attempt.write_text(json.dumps(ready_spec(), ensure_ascii=False), encoding="utf-8")
    batch_pipeline.accept_ai_paper(manifest_path, "paper001", attempt)

    captured: dict[str, object] = {}

    def fail_after_capture(**kwargs: object) -> None:
        captured.update(kwargs)
        raise RuntimeError("stop after capture")

    monkeypatch.setattr(batch_pipeline, "run_full_pipeline", fail_after_capture)
    result = batch_pipeline.build_papers(
        manifest_path,
        "paper001",
        max_alignment_passes=4,
    )
    assert captured["max_alignment_passes"] == 4
    assert result["papers"]["paper001"]["status"] == "failed"


def test_batch_build_rejects_negative_alignment_pass_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="zero or greater"):
        batch_pipeline.build_papers(tmp_path / "missing.json", max_alignment_passes=-1)
