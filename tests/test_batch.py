from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

import answercard.batch as batch


NOW = datetime(2026, 7, 14, 9, 8, 7, tzinfo=timezone.utc)


def _inputs(tmp_path: Path, *names: str) -> Path:
    source = tmp_path / "inputs"
    source.mkdir()
    for index, name in enumerate(names, start=1):
        (source / name).write_bytes(f"%PDF-{index}".encode())
    return source


def test_arbitrary_pdf_names_are_first_level_sorted_and_numbered(tmp_path: Path) -> None:
    source = _inputs(tmp_path, "Zeta 详解.PDF", "普通卷答案.pdf", "alpha-参考答案.pdf")
    nested = source / "nested"
    nested.mkdir()
    (nested / "ignored.pdf").write_bytes(b"%PDF")

    manifest = batch.create_batch_manifest(source, tmp_path / "out", now=NOW)

    assert [paper["id"] for paper in manifest["papers"]] == [
        "paper001",
        "paper002",
        "paper003",
    ]
    assert [paper["source"]["filename"] for paper in manifest["papers"]] == [
        "alpha-参考答案.pdf",
        "Zeta 详解.PDF",
        "普通卷答案.pdf",
    ]
    assert [paper["title"] for paper in manifest["papers"]] == [
        "alpha答题卡",
        "Zeta答题卡",
        "普通卷答题卡",
    ]
    assert all(len(paper["source"]["sha256"]) == 64 for paper in manifest["papers"])


def test_default_output_collision_gets_paper_suffix(tmp_path: Path) -> None:
    source = _inputs(tmp_path, "同名答案.pdf", "同名详解.pdf")

    manifest = batch.create_batch_manifest(source, tmp_path / "out", now=NOW)

    assert [paper["output_name"] for paper in manifest["papers"]] == [
        "同名答题卡.pdf",
        "同名答题卡-paper002.pdf",
    ]


def test_metadata_overrides_and_rejects_unknown_or_duplicate_names(tmp_path: Path) -> None:
    source = _inputs(tmp_path, "a.pdf", "b.pdf")
    metadata = source / "answercard-batch.yaml"
    metadata.write_text(
        """schema_version: 1
papers:
  a.pdf:
    title: 定制标题
    output_name: card-a.pdf
""",
        encoding="utf-8",
    )
    manifest = batch.create_batch_manifest(source, tmp_path / "out", now=NOW)
    assert manifest["papers"][0]["title"] == "定制标题"
    assert manifest["papers"][0]["output_name"] == "card-a.pdf"

    metadata.write_text(
        """schema_version: 1
papers:
  missing.pdf:
    title: 无效
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown PDF"):
        batch.create_batch_manifest(source, tmp_path / "out2", now=NOW)

    metadata.write_text(
        """schema_version: 1
papers:
  a.pdf: {output_name: Same.pdf}
  b.pdf: {output_name: same.PDF}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate explicit"):
        batch.create_batch_manifest(source, tmp_path / "out3", now=NOW)


def test_metadata_rejects_unknown_fields_and_non_mapping(tmp_path: Path) -> None:
    source = _inputs(tmp_path, "a.pdf")
    metadata = source / "answercard-batch.yaml"
    metadata.write_text("schema_version: 1\npapers: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        batch.create_batch_manifest(source, tmp_path / "out", now=NOW)

    metadata.write_text(
        "schema_version: 1\npapers:\n  a.pdf:\n    note: forbidden\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown fields"):
        batch.create_batch_manifest(source, tmp_path / "out2", now=NOW)


def test_run_directory_never_overwrites_and_output_cannot_be_inside_input(tmp_path: Path) -> None:
    source = _inputs(tmp_path, "a.pdf")
    first = batch.create_batch_manifest(source, tmp_path / "out", now=NOW)
    Path(first["run_dir"]).mkdir(parents=True)
    second = batch.create_batch_manifest(source, tmp_path / "out", now=NOW)
    assert second["run_dir"].endswith("-02")
    with pytest.raises(ValueError, match="must not be inside"):
        batch.create_batch_manifest(source, source / "outputs", now=NOW)


def test_manifest_is_exclusive_and_source_fingerprint_detects_change(tmp_path: Path) -> None:
    source = _inputs(tmp_path, "a.pdf")
    manifest = batch.create_batch_manifest(source, tmp_path / "out", now=NOW)
    manifest_path = Path(manifest["run_dir"]) / "batch_manifest.json"
    batch.write_batch_manifest(manifest, manifest_path)
    with pytest.raises(FileExistsError):
        batch.write_batch_manifest(manifest, manifest_path)
    assert batch.load_batch_manifest(manifest_path, verify_sources=True) == manifest
    (source / "a.pdf").write_bytes(b"changed")
    assert batch.verify_source_fingerprints(manifest) == ["paper001"]
    with pytest.raises(ValueError, match="fingerprint changed"):
        batch.load_batch_manifest(manifest_path, verify_sources=True)


def test_job_schema_locks_attempt_and_owned_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(batch, "_project_temp_root", lambda: tmp_path / "temp")
    source = _inputs(tmp_path, "a.pdf")
    manifest = batch.create_batch_manifest(source, tmp_path / "out", now=NOW)
    paper = manifest["papers"][0]
    workspace = Path(paper["workspace"])
    evidence = Path(paper["evidence_dir"]) / "source-pages"
    prompt = tmp_path / "prompts" / "ai_layout_judge.md"
    job = batch.make_ai_layout_job(
        manifest,
        "paper001",
        attempt=1,
        prompt_path=prompt,
        outline_path=workspace / "outline.json",
        skeleton_path=workspace / "ai_layout.skeleton.json",
        source_pages_dir=evidence,
        page_count=2,
    )
    assert job["allowed_output_path"].endswith("ai_layout.attempt-1.json")

    escaped = dict(job, allowed_output_path=str(tmp_path / "escape.json"))
    with pytest.raises(ValueError, match="outside its assigned path"):
        batch.validate_ai_layout_job(escaped, manifest)
    with pytest.raises(ValueError, match="unknown fields"):
        batch.validate_ai_layout_job(dict(job, visual_description="forbidden"), manifest)


def test_state_machine_is_atomic_and_rejects_illegal_transitions(tmp_path: Path) -> None:
    source = _inputs(tmp_path, "a.pdf")
    manifest = batch.create_batch_manifest(source, tmp_path / "out", now=NOW)
    state = batch.initial_batch_state(manifest)
    batch.transition_paper(state, "paper001", "awaiting_ai_layout")
    batch.transition_paper(state, "paper001", "ai_layout_running")
    batch.transition_paper(
        state,
        "paper001",
        "awaiting_ai_layout",
        attempt=2,
        error_code="AI_INVALID_JSON",
    )
    path = tmp_path / "state.json"
    batch.write_batch_state(state, path, manifest)
    assert json.loads(path.read_text(encoding="utf-8"))["papers"]["paper001"]["attempt"] == 2
    assert not list(tmp_path.glob(".*state*.tmp"))
    with pytest.raises(ValueError, match="illegal batch transition"):
        batch.transition_paper(state, "paper001", "validated")
