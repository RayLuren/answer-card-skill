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

from answercard.ai_paper_schema import (
    NEEDS_HUMAN_REVIEW,
    READY,
    ai_paper_audit,
    load_ai_paper_spec,
    validate_human_confirmation,
)
from answercard.batch import (
    RECOVERABLE_AI_CODES,
    TERMINAL_STATUSES,
    atomic_write_json,
    create_batch_manifest,
    initial_batch_state,
    load_ai_paper_job,
    load_batch_manifest,
    load_batch_state,
    make_ai_paper_job,
    paper_by_id,
    safe_error,
    transition_paper,
    validate_ai_paper_job,
    verify_source_fingerprints,
    write_ai_paper_job,
    write_batch_manifest,
    write_batch_state,
)
from answercard.frame_alignment import DEFAULT_MAX_ALIGNMENT_PASSES
from answercard.pipeline_timing import PipelineTimer
from answercard.task_report import write_task_report
from finalize_pipeline import finalize_pipeline
from full_pipeline import run_full_pipeline
from render_pages import render_pdf_pages


PROMPT_PATH = PROJECT_ROOT / "prompts" / "ai_paper_visual_extract.md"
TEMP_ROOT = PROJECT_ROOT / ".tmp"
DEFAULT_EVIDENCE_DPI = 180
_RETRYABLE_FAIL_CODES = RECOVERABLE_AI_CODES | {"TOOL_INTERRUPTED", "TEMP_READ_FAILED"}


def prepare_batch(
    input_dir: Path,
    output_root: Path,
    *,
    metadata_path: Path | None = None,
    visual_workers: int | None = None,
    evidence_dpi: int = DEFAULT_EVIDENCE_DPI,
) -> Path:
    """Fingerprint PDFs, render page PNGs, and create no-text visual jobs."""

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
            source_pages = Path(paper["evidence_dir"]) / "source-pages"
            pages = timer.run(
                "render_source_pages",
                render_pdf_pages,
                paper["source"]["path"],
                source_pages,
                dpi=evidence_dpi,
            )
            job = make_ai_paper_job(
                manifest,
                paper_id,
                attempt=1,
                revision=0,
                prompt_path=PROMPT_PATH,
                source_pages_dir=source_pages,
                page_count=len(pages),
            )
            job_path = workspace / "ai_paper_job.revision-0.attempt-1.json"
            write_ai_paper_job(job, job_path, manifest)
            state["papers"][paper_id]["job_path"] = str(job_path)
            transition_paper(state, paper_id, "awaiting_ai_paper")
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
    for paper_id in verify_source_fingerprints(manifest):
        if state["papers"][paper_id]["status"] not in TERMINAL_STATUSES:
            _terminal_failure(manifest, state, paper_id, "SOURCE_CHANGED")
    write_batch_state(state, state_path, manifest)
    return _public_status(manifest, state)


def accept_ai_paper(
    manifest_path: Path,
    paper_id: str,
    attempt_json: Path,
) -> dict[str, Any]:
    manifest = load_batch_manifest(manifest_path)
    state_path = Path(manifest["run_dir"]) / "batch_state.json"
    state = load_batch_state(state_path, manifest)
    paper = paper_by_id(manifest, paper_id)
    current = state["papers"][paper_id]
    if current["status"] in TERMINAL_STATUSES:
        return _public_status(manifest, state)
    if current["status"] != "awaiting_ai_paper":
        raise ValueError(f"paper {paper_id} is not awaiting whole-paper visual AI output")
    if paper_id in verify_source_fingerprints(manifest):
        _terminal_failure(manifest, state, paper_id, "SOURCE_CHANGED")
        write_batch_state(state, state_path, manifest)
        return _public_status(manifest, state)

    transition_paper(state, paper_id, "ai_paper_running")
    write_batch_state(state, state_path, manifest)
    try:
        job = load_ai_paper_job(current["job_path"], manifest)
    except (OSError, ValueError, json.JSONDecodeError):
        return _handle_ai_rejection(manifest, state, state_path, paper_id, "TEMP_READ_FAILED", None)
    expected_output = Path(job["allowed_output_path"]).resolve()
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
        validated = load_ai_paper_spec(candidate, page_count=job["page_count"])
    except json.JSONDecodeError:
        return _handle_ai_rejection(manifest, state, state_path, paper_id, "AI_INVALID_JSON", candidate)
    except (OSError, ValueError):
        return _handle_ai_rejection(manifest, state, state_path, paper_id, "AI_SCHEMA_INVALID", candidate)

    timer = PipelineTimer(Path(paper["workspace"]) / "pipeline_report.json")
    timer.update_result(
        {
            **ai_paper_audit(validated),
            "ai_attempt": current["attempt"],
            "ai_revision": current["revision"],
            "human_confirmation_rounds": current["revision"],
            "source_pdf_sha256": paper["source"]["sha256"],
            "source_page_count": job["page_count"],
        }
    )
    if validated["status"] == NEEDS_HUMAN_REVIEW:
        review_revision = current["revision"] + 1
        review_path = Path(paper["workspace"]) / f"human_review.revision-{review_revision}.json"
        atomic_write_json(review_path, validated)
        current["revision"] = review_revision
        current["review_path"] = str(review_path)
        current["confirmation_path"] = None
        transition_paper(state, paper_id, "needs_human_review")
        transition_paper(state, paper_id, "awaiting_human_confirmation")
    elif validated["status"] == READY:
        formal = Path(paper["workspace"]) / "ai_paper_spec.json"
        atomic_write_json(formal, validated)
        transition_paper(state, paper_id, "ai_paper_valid")
    else:  # defensive; schema currently prevents this
        raise ValueError("unsupported ai_paper_spec status")
    write_batch_state(state, state_path, manifest)
    return _public_status(manifest, state)


def confirm_ai_paper(
    manifest_path: Path,
    paper_id: str,
    confirmation_json: Path,
) -> dict[str, Any]:
    """Freeze one exact confirmation revision and create a fresh visual job."""

    manifest = load_batch_manifest(manifest_path)
    state_path = Path(manifest["run_dir"]) / "batch_state.json"
    state = load_batch_state(state_path, manifest)
    paper = paper_by_id(manifest, paper_id)
    current = state["papers"][paper_id]
    if current["status"] != "awaiting_human_confirmation":
        raise ValueError(f"paper {paper_id} is not awaiting human confirmation")
    if paper_id in verify_source_fingerprints(manifest):
        _terminal_failure(manifest, state, paper_id, "SOURCE_CHANGED")
        write_batch_state(state, state_path, manifest)
        return _public_status(manifest, state)
    try:
        review = json.loads(Path(current["review_path"]).read_text(encoding="utf-8"))
        confirmation = json.loads(confirmation_json.read_text(encoding="utf-8"))
        validated = validate_human_confirmation(
            confirmation,
            paper_id=paper_id,
            revision=current["revision"],
            review_items=review["review_items"],
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"human confirmation is invalid: {exc}") from exc

    workspace = Path(paper["workspace"])
    frozen = workspace / f"human_confirmation.revision-{current['revision']}.json"
    if frozen.exists():
        raise ValueError(f"human confirmation revision already exists: {frozen}")
    atomic_write_json(frozen, validated)
    prior_job = load_ai_paper_job(current["job_path"], manifest)
    job = make_ai_paper_job(
        manifest,
        paper_id,
        attempt=1,
        revision=current["revision"],
        prompt_path=prior_job["prompt_path"],
        source_pages_dir=prior_job["source_pages_dir"],
        page_count=prior_job["page_count"],
        human_confirmation_path=frozen,
    )
    job_path = workspace / f"ai_paper_job.revision-{current['revision']}.attempt-1.json"
    write_ai_paper_job(job, job_path, manifest)
    current["attempt"] = 1
    current["job_path"] = str(job_path)
    current["confirmation_path"] = str(frozen)
    transition_paper(state, paper_id, "awaiting_ai_paper")
    write_batch_state(state, state_path, manifest)
    return _public_status(manifest, state)


def fail_paper(manifest_path: Path, paper_id: str, code: str) -> dict[str, Any]:
    safe_error(code)
    manifest = load_batch_manifest(manifest_path)
    state_path = Path(manifest["run_dir"]) / "batch_state.json"
    state = load_batch_state(state_path, manifest)
    current = state["papers"][paper_id]
    if current["status"] in TERMINAL_STATUSES:
        return _public_status(manifest, state)
    if (
        code in _RETRYABLE_FAIL_CODES
        and current["attempt"] == 1
        and current["status"] in {"awaiting_ai_paper", "ai_paper_running"}
    ):
        if current["status"] == "awaiting_ai_paper":
            transition_paper(state, paper_id, "ai_paper_running")
        try:
            _prepare_retry(manifest, state, paper_id, code)
        except (OSError, ValueError, json.JSONDecodeError):
            _terminal_failure(manifest, state, paper_id, "TEMP_READ_FAILED")
    else:
        _terminal_failure(manifest, state, paper_id, code)
    write_batch_state(state, state_path, manifest)
    return _public_status(manifest, state)


def build_papers(
    manifest_path: Path,
    paper_id: str | None = None,
    *,
    max_alignment_passes: int = DEFAULT_MAX_ALIGNMENT_PASSES,
) -> dict[str, Any]:
    if isinstance(max_alignment_passes, bool) or not isinstance(max_alignment_passes, int):
        raise ValueError("max_alignment_passes must be an integer")
    if max_alignment_passes < 0:
        raise ValueError("max_alignment_passes must be zero or greater")
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
        if current["status"] != "ai_paper_valid":
            continue
        transition_paper(state, current_id, "building")
        write_batch_state(state, state_path, manifest)
        workspace = Path(paper["workspace"])
        published: Path | None = None
        try:
            job = load_ai_paper_job(current["job_path"], manifest)
            run_full_pipeline(
                paper_title=paper["title"],
                ai_paper_path=workspace / "ai_paper_spec.json",
                source_page_count=job["page_count"],
                visual_requirements_path=workspace / "visual_requirements.json",
                qspec_path=workspace / "qspec.yaml",
                build_dir=workspace,
                pages_dir=workspace / "pages",
                report_path=workspace / "pipeline_report.json",
                max_alignment_passes=max_alignment_passes,
            )
            finalize_pipeline(
                ai_paper_path=workspace / "ai_paper_spec.json",
                ai_page_count=job["page_count"],
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
        raise ValueError("formal batch report requires every paper to be validated or failed")
    task_report = run_dir / "task-report.md"
    run_report = run_dir / "run-report.json"
    if task_report.is_file() and run_report.is_file():
        _remove_empty_batch_temp(manifest)
        return task_report
    reports: list[Path] = []
    for paper in manifest["papers"]:
        current = state["papers"][paper["id"]]
        report_path = Path(current["report_path"])
        if not report_path.is_file():
            _write_synthetic_failure_report(report_path, paper["title"], current["error"])
        reports.append(report_path)
    if not task_report.exists():
        write_task_report(reports, task_report)
    if not run_report.exists():
        atomic_write_json(
            run_report,
            {
                "schema_version": 1,
                "batch_id": manifest["batch_id"],
                "input_count": len(manifest["papers"]),
                "success_count": sum(item["status"] == "validated" for item in state["papers"].values()),
                "failure_count": sum(item["status"] == "failed" for item in state["papers"].values()),
                "concurrency": manifest["concurrency"],
                "papers": [
                    {
                        "id": paper["id"],
                        "status": state["papers"][paper["id"]]["status"],
                        "revision": state["papers"][paper["id"]]["revision"],
                        "output_file": (
                            Path(state["papers"][paper["id"]]["published_pdf"]).name
                            if state["papers"][paper["id"]]["published_pdf"] else None
                        ),
                        "error_code": (
                            state["papers"][paper["id"]]["error"]["code"]
                            if state["papers"][paper["id"]]["error"] else None
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
    current = state["papers"][paper_id]
    prior = validate_ai_paper_job(
        json.loads(Path(current["job_path"]).read_text(encoding="utf-8")),
        manifest,
    )
    source_pages = Path(prior["source_pages_dir"])
    actual_pages = sorted(source_pages.glob("page-*.png")) if source_pages.is_dir() else []
    if len(actual_pages) != prior["page_count"]:
        rendered = render_pdf_pages(prior["source_pdf"], source_pages, dpi=DEFAULT_EVIDENCE_DPI)
        prior["page_count"] = len(rendered)
    job = make_ai_paper_job(
        manifest,
        paper_id,
        attempt=2,
        revision=current["revision"],
        prompt_path=prior["prompt_path"],
        source_pages_dir=prior["source_pages_dir"],
        page_count=prior["page_count"],
        human_confirmation_path=prior["human_confirmation_path"],
    )
    job_path = Path(paper["workspace"]) / f"ai_paper_job.revision-{current['revision']}.attempt-2.json"
    write_ai_paper_job(job, job_path, manifest)
    transition_paper(state, paper_id, "awaiting_ai_paper", attempt=2, error_code=code)
    current["job_path"] = str(job_path)


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
    try:
        data = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
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
        if isinstance(stage, dict) and stage.get("status") in {"failed", "running"}:
            stage.pop("_started_epoch_seconds", None)
            stage["status"] = "failed"
            stage.setdefault("error", f"{error['code']}: {error['message']}")
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
                "revision": item["revision"],
                "job_path": item["job_path"],
                "review_path": item["review_path"],
                "confirmation_path": item["confirmation_path"],
                "published_pdf": item["published_pdf"],
                "error": item["error"],
            }
            for paper_id, item in state["papers"].items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a resumable whole-paper visual AI batch.")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("input_dir", type=Path)
    prepare.add_argument("output_root", type=Path)
    prepare.add_argument("--metadata", type=Path, default=None)
    prepare.add_argument("--visual-workers", type=int, default=None)
    prepare.add_argument("--evidence-dpi", type=int, default=DEFAULT_EVIDENCE_DPI)
    status = commands.add_parser("status")
    status.add_argument("manifest", type=Path)
    accept = commands.add_parser("accept-ai-paper")
    accept.add_argument("manifest", type=Path)
    accept.add_argument("paper_id")
    accept.add_argument("attempt_json", type=Path)
    confirm = commands.add_parser("confirm-ai-paper")
    confirm.add_argument("manifest", type=Path)
    confirm.add_argument("paper_id")
    confirm.add_argument("confirmation_json", type=Path)
    build = commands.add_parser("build")
    build.add_argument("manifest", type=Path)
    build.add_argument("--paper", default=None)
    build.add_argument(
        "--max-alignment-passes",
        type=int,
        default=DEFAULT_MAX_ALIGNMENT_PASSES,
    )
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
        elif args.command == "accept-ai-paper":
            result = accept_ai_paper(args.manifest, args.paper_id, args.attempt_json)
        elif args.command == "confirm-ai-paper":
            result = confirm_ai_paper(args.manifest, args.paper_id, args.confirmation_json)
        elif args.command == "build":
            result = build_papers(
                args.manifest,
                args.paper,
                max_alignment_passes=args.max_alignment_passes,
            )
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
