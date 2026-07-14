from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

from answercard.ai_layout_audit import audit_ai_layout_handoff
from answercard.ai_layout_schema import load_ai_layout
from answercard.ai_layout_skeleton import write_ai_layout_skeleton
from answercard.batch import (
    RECOVERABLE_AI_CODES,
    TERMINAL_STATUSES,
    atomic_write_json,
    create_batch_manifest,
    initial_batch_state,
    load_ai_layout_job,
    load_batch_manifest,
    load_batch_state,
    make_ai_layout_job,
    paper_by_id,
    safe_error,
    transition_paper,
    validate_ai_layout_job,
    verify_source_fingerprints,
    write_ai_layout_job,
    write_batch_manifest,
    write_batch_state,
)
from answercard.extract_outline import extract_outline
from answercard.pipeline_timing import PipelineTimer
from answercard.task_report import write_task_report
from finalize_pipeline import finalize_pipeline
from full_pipeline import run_full_pipeline
from render_pages import render_pdf_pages


PROMPT_PATH = PROJECT_ROOT / "prompts" / "ai_layout_judge.md"
TEMP_ROOT = PROJECT_ROOT / ".tmp"
_RETRYABLE_FAIL_CODES = RECOVERABLE_AI_CODES | {"TOOL_INTERRUPTED", "TEMP_READ_FAILED"}


def prepare_batch(
    input_dir: Path,
    output_root: Path,
    *,
    metadata_path: Path | None = None,
    visual_workers: int | None = None,
    evidence_dpi: int = 120,
) -> Path:
    manifest = create_batch_manifest(
        input_dir,
        output_root,
        metadata_path=metadata_path,
        visual_workers=visual_workers,
    )
    run_dir = Path(manifest["run_dir"])
    for directory in (run_dir / ".work", run_dir / "audit", run_dir / "failed"):
        directory.mkdir(parents=True, exist_ok=True)
    manifest_path = write_batch_manifest(manifest, run_dir / "batch_manifest.json")
    state_path = run_dir / "batch_state.json"
    state = initial_batch_state(manifest)
    write_batch_state(state, state_path, manifest)

    for paper in manifest["papers"]:
        paper_id = paper["id"]
        workspace = Path(paper["workspace"])
        workspace.mkdir(parents=True, exist_ok=False)
        report_path = workspace / "pipeline_report.json"
        timer = PipelineTimer(report_path)
        timer.begin(label=paper["title"], reset=True)
        try:
            outline_path = workspace / "outline.json"
            timer.run("extract_outline", extract_outline, paper["source"]["path"], outline_path)
            skeleton_path = workspace / "ai_layout.skeleton.json"
            timer.run(
                "prepare_ai_layout_skeleton",
                write_ai_layout_skeleton,
                outline_path,
                skeleton_path,
            )
            source_pages = Path(paper["evidence_dir"]) / "source-pages"
            pages = timer.run(
                "render_source_pages",
                render_pdf_pages,
                paper["source"]["path"],
                source_pages,
                dpi=evidence_dpi,
            )
            job = make_ai_layout_job(
                manifest,
                paper_id,
                attempt=1,
                prompt_path=PROMPT_PATH,
                outline_path=outline_path,
                skeleton_path=skeleton_path,
                source_pages_dir=source_pages,
                page_count=len(pages),
            )
            job_path = workspace / "ai_layout_job.attempt-1.json"
            write_ai_layout_job(job, job_path, manifest)
            state["papers"][paper_id]["job_path"] = str(job_path)
            transition_paper(state, paper_id, "awaiting_ai_layout")
        except Exception:
            _finish_pipeline_failure(report_path, "TEMP_READ_FAILED")
            transition_paper(state, paper_id, "failed", error_code="TEMP_READ_FAILED")
            _cleanup_evidence(paper)
            archive = _archive_workspace(paper, failed=True)
            state["papers"][paper_id]["archive_path"] = str(archive)
            state["papers"][paper_id]["report_path"] = str(archive / "pipeline_report.json")
        write_batch_state(state, state_path, manifest)
    return manifest_path


def batch_status(manifest_path: Path) -> dict[str, Any]:
    manifest = load_batch_manifest(manifest_path)
    state_path = Path(manifest["run_dir"]) / "batch_state.json"
    state = load_batch_state(state_path, manifest)
    changed = set(verify_source_fingerprints(manifest))
    if changed:
        for paper_id in changed:
            if state["papers"][paper_id]["status"] not in TERMINAL_STATUSES:
                _terminal_failure(manifest, state, paper_id, "SOURCE_CHANGED")
        write_batch_state(state, state_path, manifest)
    return _public_status(manifest, state)


def accept_ai_layout(
    manifest_path: Path,
    paper_id: str,
    attempt_json: Path,
) -> dict[str, Any]:
    manifest = load_batch_manifest(manifest_path)
    state_path = Path(manifest["run_dir"]) / "batch_state.json"
    state = load_batch_state(state_path, manifest)
    paper = paper_by_id(manifest, paper_id)
    paper_state = state["papers"][paper_id]
    if paper_state["status"] in TERMINAL_STATUSES:
        return _public_status(manifest, state)
    if paper_state["status"] != "awaiting_ai_layout":
        raise ValueError(f"paper {paper_id} is not awaiting AI layout")
    if paper_id in verify_source_fingerprints(manifest):
        _terminal_failure(manifest, state, paper_id, "SOURCE_CHANGED")
        write_batch_state(state, state_path, manifest)
        return _public_status(manifest, state)

    transition_paper(state, paper_id, "ai_layout_running")
    write_batch_state(state, state_path, manifest)
    try:
        expected_job = load_ai_layout_job(paper_state["job_path"], manifest)
    except (OSError, ValueError, json.JSONDecodeError):
        return _handle_ai_rejection(
            manifest, state, state_path, paper_id, "TEMP_READ_FAILED", None
        )
    expected_output = Path(expected_job["allowed_output_path"]).resolve()
    candidate = attempt_json.resolve()
    if candidate != expected_output or not candidate.is_file():
        return _handle_ai_rejection(
            manifest,
            state,
            state_path,
            paper_id,
            "AI_OUTPUT_MISSING",
            candidate if candidate == expected_output else None,
        )

    try:
        validated = load_ai_layout(candidate)
    except json.JSONDecodeError:
        return _handle_ai_rejection(
            manifest, state, state_path, paper_id, "AI_INVALID_JSON", candidate
        )
    except (OSError, ValueError):
        return _handle_ai_rejection(
            manifest, state, state_path, paper_id, "AI_SCHEMA_INVALID", candidate
        )

    try:
        audit = audit_ai_layout_handoff(Path(paper["workspace"]) / "outline.json", candidate)
    except (OSError, ValueError, json.JSONDecodeError):
        return _handle_ai_rejection(
            manifest, state, state_path, paper_id, "TEMP_READ_FAILED", candidate
        )
    if (
        audit["ai_layout_conflicts"]
        or audit["reinspection_required_items"]
        or audit["invalid_fallback_items"]
    ):
        _terminal_failure(manifest, state, paper_id, "AI_LAYOUT_CONFLICT")
        write_batch_state(state, state_path, manifest)
        return _public_status(manifest, state)

    formal = Path(paper["workspace"]) / "ai_layout.json"
    atomic_write_json(formal, validated)
    transition_paper(state, paper_id, "ai_layout_valid")
    write_batch_state(state, state_path, manifest)
    return _public_status(manifest, state)


def fail_paper(manifest_path: Path, paper_id: str, code: str) -> dict[str, Any]:
    safe_error(code)
    manifest = load_batch_manifest(manifest_path)
    state_path = Path(manifest["run_dir"]) / "batch_state.json"
    state = load_batch_state(state_path, manifest)
    paper_state = state["papers"][paper_id]
    if paper_state["status"] in TERMINAL_STATUSES:
        return _public_status(manifest, state)
    if (
        code in _RETRYABLE_FAIL_CODES
        and paper_state["attempt"] == 1
        and paper_state["status"] in {"awaiting_ai_layout", "ai_layout_running"}
    ):
        if paper_state["status"] == "awaiting_ai_layout":
            transition_paper(state, paper_id, "ai_layout_running")
        try:
            _prepare_retry(manifest, state, paper_id, code)
        except (OSError, ValueError, json.JSONDecodeError):
            _terminal_failure(manifest, state, paper_id, "TEMP_READ_FAILED")
    else:
        _terminal_failure(manifest, state, paper_id, code)
    write_batch_state(state, state_path, manifest)
    return _public_status(manifest, state)


def build_papers(manifest_path: Path, paper_id: str | None = None) -> dict[str, Any]:
    manifest = load_batch_manifest(manifest_path)
    state_path = Path(manifest["run_dir"]) / "batch_state.json"
    state = load_batch_state(state_path, manifest)
    targets = manifest["papers"] if paper_id is None else [paper_by_id(manifest, paper_id)]
    changed = set(verify_source_fingerprints(manifest))

    for paper in targets:
        current_id = paper["id"]
        current = state["papers"][current_id]
        if current["status"] in TERMINAL_STATUSES:
            continue
        if current_id in changed:
            _terminal_failure(manifest, state, current_id, "SOURCE_CHANGED")
            write_batch_state(state, state_path, manifest)
            continue
        if current["status"] != "ai_layout_valid":
            continue

        transition_paper(state, current_id, "building")
        write_batch_state(state, state_path, manifest)
        workspace = Path(paper["workspace"])
        published: Path | None = None
        try:
            run_full_pipeline(
                paper["source"]["path"],
                paper_title=paper["title"],
                outline_path=workspace / "outline.json",
                ai_layout_path=workspace / "ai_layout.json",
                visual_requirements_path=workspace / "visual_requirements.json",
                qspec_path=workspace / "qspec.yaml",
                build_dir=workspace,
                pages_dir=workspace / "pages",
                report_path=workspace / "pipeline_report.json",
            )
            finalize_pipeline(
                qspec_path=workspace / "qspec.yaml",
                pdf_path=workspace / "answercard.pdf",
                pages_dir=workspace / "pages",
                build_dir=workspace,
                alignment_report_path=workspace / "frame_alignment.json",
                visual_requirements_path=workspace / "visual_requirements.json",
                report_path=workspace / "pipeline_report.json",
                log_paths=(workspace / "answercard.log",),
                front_pages=1,
                temp_paths=(paper["evidence_dir"],),
                temp_root=TEMP_ROOT,
            )
            published, archive = _publish_success(paper)
            current["published_pdf"] = str(published)
            current["archive_path"] = str(archive)
            current["report_path"] = str(archive / "pipeline_report.json")
            transition_paper(state, current_id, "validated")
        except Exception:
            if published is not None and published.exists():
                published.unlink()
            _terminal_failure(manifest, state, current_id, "BUILD_FAILED")
        write_batch_state(state, state_path, manifest)
    return _public_status(manifest, state)


def write_batch_report(manifest_path: Path) -> Path:
    manifest = load_batch_manifest(manifest_path)
    run_dir = Path(manifest["run_dir"])
    state = load_batch_state(run_dir / "batch_state.json", manifest)
    if any(item["status"] not in TERMINAL_STATUSES for item in state["papers"].values()):
        raise ValueError("batch report requires every paper to be validated or failed")
    task_report = run_dir / "task-report.md"
    run_report = run_dir / "run-report.json"
    if task_report.is_file() and run_report.is_file():
        _remove_empty_batch_temp(manifest)
        return task_report

    report_paths: list[Path] = []
    for paper in manifest["papers"]:
        paper_state = state["papers"][paper["id"]]
        report_path = Path(paper_state["report_path"])
        if not report_path.is_file():
            _write_synthetic_failure_report(report_path, paper["title"], paper_state["error"])
        report_paths.append(report_path)
    if not task_report.exists():
        write_task_report(report_paths, task_report)
    if not run_report.exists():
        validated = [
            paper_id for paper_id, item in state["papers"].items() if item["status"] == "validated"
        ]
        failed = [paper_id for paper_id, item in state["papers"].items() if item["status"] == "failed"]
        outputs = [
            state["papers"][paper["id"]]["published_pdf"]
            for paper in manifest["papers"]
            if state["papers"][paper["id"]]["published_pdf"]
        ]
        atomic_write_json(
            run_report,
            {
                "schema_version": 1,
                "batch_id": manifest["batch_id"],
                "input_count": len(manifest["papers"]),
                "success_count": len(validated),
                "failure_count": len(failed),
                "output_files": [Path(path).name for path in outputs],
                "concurrency": manifest["concurrency"],
                "papers": [
                    {
                        "id": paper["id"],
                        "status": state["papers"][paper["id"]]["status"],
                        "output_file": (
                            Path(state["papers"][paper["id"]]["published_pdf"]).name
                            if state["papers"][paper["id"]]["published_pdf"]
                            else None
                        ),
                        "error_code": (
                            state["papers"][paper["id"]]["error"]["code"]
                            if state["papers"][paper["id"]]["error"]
                            else None
                        ),
                    }
                    for paper in manifest["papers"]
                ],
            },
        )
    _remove_empty_batch_temp(manifest)
    return task_report


def _handle_ai_rejection(
    manifest: dict[str, Any],
    state: dict[str, Any],
    state_path: Path,
    paper_id: str,
    code: str,
    candidate: Path | None,
) -> dict[str, Any]:
    if candidate is not None and candidate.exists():
        candidate.unlink()
    if state["papers"][paper_id]["attempt"] == 1:
        try:
            _prepare_retry(manifest, state, paper_id, code)
        except (OSError, ValueError, json.JSONDecodeError):
            _terminal_failure(manifest, state, paper_id, "TEMP_READ_FAILED")
    else:
        _terminal_failure(manifest, state, paper_id, "AI_RETRY_EXHAUSTED")
    write_batch_state(state, state_path, manifest)
    return _public_status(manifest, state)


def _prepare_retry(
    manifest: dict[str, Any],
    state: dict[str, Any],
    paper_id: str,
    code: str,
) -> None:
    paper = paper_by_id(manifest, paper_id)
    prior_job_path = Path(state["papers"][paper_id]["job_path"])
    prior_job = validate_ai_layout_job(
        json.loads(prior_job_path.read_text(encoding="utf-8")),
        manifest,
    )
    source_pages = Path(prior_job["source_pages_dir"])
    actual_pages = sorted(source_pages.glob("page-*.png")) if source_pages.is_dir() else []
    if len(actual_pages) != prior_job["page_count"]:
        rendered = render_pdf_pages(
            prior_job["source_pdf"],
            source_pages,
            dpi=120,
        )
        prior_job["page_count"] = len(rendered)
    job = make_ai_layout_job(
        manifest,
        paper_id,
        attempt=2,
        prompt_path=prior_job["prompt_path"],
        outline_path=prior_job["outline_path"],
        skeleton_path=prior_job["skeleton_path"],
        source_pages_dir=prior_job["source_pages_dir"],
        page_count=prior_job["page_count"],
    )
    job_path = Path(paper["workspace"]) / "ai_layout_job.attempt-2.json"
    write_ai_layout_job(job, job_path, manifest)
    transition_paper(state, paper_id, "awaiting_ai_layout", attempt=2, error_code=code)
    state["papers"][paper_id]["job_path"] = str(job_path)


def _terminal_failure(
    manifest: dict[str, Any],
    state: dict[str, Any],
    paper_id: str,
    code: str,
) -> None:
    paper = paper_by_id(manifest, paper_id)
    current = state["papers"][paper_id]
    if current["status"] in TERMINAL_STATUSES:
        return
    transition_paper(state, paper_id, "failed", error_code=code)
    report_path = Path(current["report_path"])
    _finish_pipeline_failure(report_path, code)
    _cleanup_evidence(paper)
    archive = _archive_workspace(paper, failed=True)
    current["archive_path"] = str(archive)
    current["report_path"] = str(archive / "pipeline_report.json")


def _finish_pipeline_failure(report_path: Path, code: str) -> None:
    error = safe_error(code)
    if report_path.is_file():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    else:
        data = {}
    data.setdefault("schema_version", 1)
    data.setdefault("label", "答题卡")
    data.setdefault("stages", [])
    data["status"] = "failed"
    data["error"] = error
    data.setdefault("result", {})
    data.setdefault("total_duration_seconds", 0.0)
    data.pop("_started_epoch_seconds", None)
    for stage in data["stages"]:
        if not isinstance(stage, dict):
            continue
        stage.pop("_started_epoch_seconds", None)
        if stage.get("status") in {"failed", "running"}:
            stage["status"] = "failed"
            stage["error"] = f"{error['code']}: {error['message']}"
            stage.setdefault("duration_seconds", 0.0)
    atomic_write_json(report_path, data)


def _write_synthetic_failure_report(path: Path, title: str, error: dict[str, str] | None) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "label": title,
            "status": "failed",
            "error": error or safe_error("BUILD_FAILED"),
            "stages": [],
            "result": {},
            "total_duration_seconds": 0.0,
        },
    )


def _cleanup_evidence(paper: dict[str, Any]) -> None:
    evidence = Path(paper["evidence_dir"])
    if evidence.exists():
        resolved_root = TEMP_ROOT.resolve()
        resolved = evidence.resolve()
        if resolved != resolved_root and resolved_root in resolved.parents:
            shutil.rmtree(resolved)


def _remove_empty_batch_temp(manifest: dict[str, Any]) -> None:
    batch_temp = TEMP_ROOT / "batches" / manifest["batch_id"]
    if not batch_temp.is_dir():
        return
    for directory in sorted(
        (path for path in batch_temp.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        batch_temp.rmdir()
    except OSError:
        pass


def _archive_workspace(paper: dict[str, Any], *, failed: bool) -> Path:
    source = Path(paper["workspace"])
    destination = Path(paper["failed_dir"] if failed else paper["audit_dir"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.exists():
        if destination.exists():
            raise ValueError(f"archive destination already exists: {destination}")
        os.replace(source, destination)
    return destination


def _publish_success(paper: dict[str, Any]) -> tuple[Path, Path]:
    workspace = Path(paper["workspace"])
    source_pdf = workspace / "answercard.pdf"
    run_dir = workspace.parents[1]
    destination = run_dir / paper["output_name"]
    temporary = run_dir / f".{paper['id']}.publish.tmp"
    shutil.copy2(source_pdf, temporary)
    archive: Path | None = None
    try:
        archive = _archive_workspace(paper, failed=False)
        os.replace(temporary, destination)
        archived_pdf = archive / "answercard.pdf"
        if archived_pdf.exists():
            archived_pdf.unlink()
    except Exception:
        if temporary.exists():
            temporary.unlink()
        if destination.exists():
            destination.unlink()
        if archive is not None and archive.exists() and not workspace.exists():
            os.replace(archive, workspace)
        raise
    return destination, archive


def _public_status(manifest: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    return {
        "batch_id": manifest["batch_id"],
        "run_dir": manifest["run_dir"],
        "concurrency": manifest["concurrency"],
        "papers": {
            paper_id: {
                "status": item["status"],
                "attempt": item["attempt"],
                "job_path": item["job_path"],
                "published_pdf": item["published_pdf"],
                "error": item["error"],
            }
            for paper_id, item in state["papers"].items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a resumable, answer-free PDF directory batch.")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("input_dir", type=Path)
    prepare.add_argument("output_root", type=Path)
    prepare.add_argument("--metadata", type=Path, default=None)
    prepare.add_argument("--visual-workers", type=int, default=None)
    prepare.add_argument("--evidence-dpi", type=int, default=120)

    status = commands.add_parser("status")
    status.add_argument("manifest", type=Path)

    accept = commands.add_parser("accept-ai-layout")
    accept.add_argument("manifest", type=Path)
    accept.add_argument("paper_id")
    accept.add_argument("attempt_json", type=Path)

    build = commands.add_parser("build")
    build.add_argument("manifest", type=Path)
    build.add_argument("--paper", default=None)

    fail = commands.add_parser("fail-paper")
    fail.add_argument("manifest", type=Path)
    fail.add_argument("paper_id")
    fail.add_argument("--code", required=True)

    report = commands.add_parser("report")
    report.add_argument("manifest", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result: object = prepare_batch(
                args.input_dir,
                args.output_root,
                metadata_path=args.metadata,
                visual_workers=args.visual_workers,
                evidence_dpi=args.evidence_dpi,
            )
        elif args.command == "status":
            result = batch_status(args.manifest)
        elif args.command == "accept-ai-layout":
            result = accept_ai_layout(args.manifest, args.paper_id, args.attempt_json)
        elif args.command == "build":
            result = build_papers(args.manifest, args.paper)
        elif args.command == "fail-paper":
            result = fail_paper(args.manifest, args.paper_id, args.code)
        else:
            result = write_batch_report(args.manifest)
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(result if isinstance(result, Path) else json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
