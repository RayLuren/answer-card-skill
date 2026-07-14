"""Host-neutral contracts for resumable answer-card batch runs."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

import yaml


BATCH_SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION = 1
JOB_SCHEMA_VERSION = 1
TERMINAL_STATUSES = {"validated", "failed"}
PAPER_STATUSES = {
    "prepared",
    "awaiting_ai_layout",
    "ai_layout_running",
    "ai_layout_valid",
    "building",
    *TERMINAL_STATUSES,
}
RECOVERABLE_AI_CODES = {"AI_INVALID_JSON", "AI_SCHEMA_INVALID", "AI_OUTPUT_MISSING"}
SAFE_ERROR_MESSAGES = {
    "AI_INVALID_JSON": "AI layout output was not valid JSON.",
    "AI_SCHEMA_INVALID": "AI layout output failed the strict schema or safety validation.",
    "AI_OUTPUT_MISSING": "AI layout output was not written to the allowed attempt path.",
    "AI_LAYOUT_CONFLICT": "AI layout conflicts with the answer-free structural outline.",
    "SOURCE_CHANGED": "The source PDF no longer matches the immutable batch manifest.",
    "CAPABILITY_UNAVAILABLE": "Required visual inspection capability is unavailable.",
    "TOOL_INTERRUPTED": "The visual worker was interrupted.",
    "TEMP_READ_FAILED": "Transient source-page evidence could not be read.",
    "AI_RETRY_EXHAUSTED": "AI layout validation failed twice.",
    "BUILD_FAILED": "The deterministic build or final validation failed.",
    "USER_ABORTED": "The paper was stopped by the batch operator.",
}

_TITLE_SUFFIX_RE = re.compile(
    r"(?:[\s._\-—–]+)?(?:参考答案|答案|详解)\s*$",
    flags=re.IGNORECASE,
)
_TRAILING_SEPARATOR_RE = re.compile(r"[\s._\-—–]+$")
_INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RUN_SLUG_RE = re.compile(r"[^\w\u3400-\u9fff-]+", flags=re.UNICODE)
_PAPER_ID_RE = re.compile(r"paper\d{3,}")
_ERROR_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{2,63}")


def create_batch_manifest(
    input_dir: str | Path,
    output_root: str | Path,
    *,
    metadata_path: str | Path | None = None,
    visual_workers: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Discover first-level PDFs and allocate a new, never-overwritten run."""

    source_dir = Path(input_dir).resolve()
    destination_root = Path(output_root).resolve()
    if not source_dir.is_dir():
        raise ValueError(f"batch input directory does not exist: {source_dir}")
    if _is_relative_to(destination_root, source_dir):
        raise ValueError("output root must not be inside the input directory")

    pdf_paths = sorted(
        (
            path.resolve()
            for path in source_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".pdf"
        ),
        key=lambda path: (path.name.casefold(), path.name),
    )
    if not pdf_paths:
        raise ValueError(f"batch input directory contains no PDF files: {source_dir}")

    metadata_file = _select_metadata_path(source_dir, metadata_path)
    overrides = load_batch_metadata(metadata_file, pdf_paths) if metadata_file else {}
    timestamp = now or datetime.now().astimezone()
    run_dir = allocate_run_directory(destination_root, source_dir.name, timestamp)
    workers = visual_workers if visual_workers is not None else 4
    if isinstance(workers, bool) or not isinstance(workers, int) or workers <= 0:
        raise ValueError("visual worker limit must be a positive integer")

    papers: list[dict[str, Any]] = []
    used_default_names: set[str] = set()
    reserved_explicit_names = {
        normalize_output_name(value["output_name"]).casefold()
        for value in overrides.values()
        if "output_name" in value
    }
    for index, pdf_path in enumerate(pdf_paths, start=1):
        paper_id = f"paper{index:03d}"
        override = overrides.get(pdf_path.name, {})
        title = override.get("title") or default_paper_title(pdf_path.stem)
        if "output_name" in override:
            output_name = normalize_output_name(override["output_name"])
        else:
            base_output = normalize_output_name(title)
            output_name = base_output
            key = output_name.casefold()
            if key in used_default_names or key in reserved_explicit_names:
                output_name = _append_paper_suffix(base_output, paper_id)
                key = output_name.casefold()
                collision = 2
                while key in used_default_names or key in reserved_explicit_names:
                    output_name = f"{Path(base_output).stem}-{paper_id}-{collision:02d}.pdf"
                    key = output_name.casefold()
                    collision += 1
            used_default_names.add(key)

        workspace = run_dir / ".work" / paper_id
        evidence_dir = _project_temp_root() / "batches" / run_dir.name / paper_id
        stat = pdf_path.stat()
        papers.append(
            {
                "id": paper_id,
                "title": title,
                "output_name": output_name,
                "source": {
                    "filename": pdf_path.name,
                    "path": str(pdf_path),
                    "size": stat.st_size,
                    "sha256": sha256_file(pdf_path),
                },
                "workspace": str(workspace),
                "evidence_dir": str(evidence_dir),
                "audit_dir": str(run_dir / "audit" / paper_id),
                "failed_dir": str(run_dir / "failed" / paper_id),
            }
        )

    return validate_batch_manifest(
        {
            "schema_version": BATCH_SCHEMA_VERSION,
            "batch_id": run_dir.name,
            "created_at": timestamp.isoformat(),
            "input_dir": str(source_dir),
            "output_root": str(destination_root),
            "run_dir": str(run_dir),
            "concurrency": {
                "visual_workers": workers,
                "source": "requested" if visual_workers is not None else "default",
                "build_workers": 1,
            },
            "papers": papers,
        }
    )


def allocate_run_directory(output_root: Path, input_name: str, now: datetime) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    slug = _run_slug(input_name)
    stem = f"run-{now.strftime('%Y%m%d-%H%M%S')}-{slug}"
    candidate = output_root / stem
    suffix = 2
    while candidate.exists():
        candidate = output_root / f"{stem}-{suffix:02d}"
        suffix += 1
    return candidate.resolve()


def load_batch_metadata(
    metadata_path: str | Path,
    pdf_paths: Iterable[Path],
) -> dict[str, dict[str, str]]:
    source = Path(metadata_path)
    if not source.is_file():
        raise ValueError(f"batch metadata does not exist: {source}")
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("batch metadata must be a mapping")
    _reject_unknown(data, {"schema_version", "papers"}, "batch metadata")
    if data.get("schema_version") != 1:
        raise ValueError("batch metadata schema_version must be 1")
    papers = data.get("papers")
    if not isinstance(papers, dict):
        raise ValueError("batch metadata papers must be a mapping")
    known = {path.name for path in pdf_paths}
    result: dict[str, dict[str, str]] = {}
    for filename, override in papers.items():
        if not isinstance(filename, str) or filename not in known:
            raise ValueError(f"batch metadata references an unknown PDF: {filename}")
        if not isinstance(override, dict):
            raise ValueError(f"batch metadata papers.{filename} must be a mapping")
        _reject_unknown(override, {"title", "output_name"}, f"papers.{filename}")
        normalized: dict[str, str] = {}
        for key, value in override.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"papers.{filename}.{key} must be a non-empty string")
            normalized[key] = value.strip()
        result[filename] = normalized

    explicit_names = [
        normalize_output_name(value["output_name"]).casefold()
        for value in result.values()
        if "output_name" in value
    ]
    if len(explicit_names) != len(set(explicit_names)):
        raise ValueError("batch metadata contains duplicate explicit output_name values")
    return result


def default_paper_title(stem: str) -> str:
    title = stem.strip()
    previous = None
    while title != previous:
        previous = title
        title = _TITLE_SUFFIX_RE.sub("", title).strip()
        title = _TRAILING_SEPARATOR_RE.sub("", title).strip()
    if not title:
        title = "试卷"
    return f"{title}答题卡"


def normalize_output_name(value: str) -> str:
    name = value.strip()
    if name.lower().endswith(".pdf"):
        name = name[:-4].rstrip()
    name = _INVALID_FILENAME_RE.sub("_", name).rstrip(" .")
    if name in {"", ".", ".."}:
        raise ValueError("output_name must contain a usable filename")
    return f"{name}.pdf"


def write_batch_manifest(data: dict[str, Any], path: str | Path) -> Path:
    validated = validate_batch_manifest(data)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_json_exclusive(destination, validated)
    return destination


def load_batch_manifest(
    path: str | Path,
    *,
    verify_sources: bool = False,
) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"batch manifest does not exist: {source}")
    data = validate_batch_manifest(json.loads(source.read_text(encoding="utf-8")))
    expected = Path(data["run_dir"]) / "batch_manifest.json"
    if source.resolve() != expected.resolve():
        raise ValueError("batch manifest path does not match its immutable run directory")
    if verify_sources:
        mismatches = verify_source_fingerprints(data)
        if mismatches:
            raise ValueError("source PDF fingerprint changed: " + ", ".join(mismatches))
    return data


def validate_batch_manifest(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("batch manifest must be an object")
    allowed = {
        "schema_version",
        "batch_id",
        "created_at",
        "input_dir",
        "output_root",
        "run_dir",
        "concurrency",
        "papers",
    }
    _reject_unknown(data, allowed, "batch manifest")
    if data.get("schema_version") != BATCH_SCHEMA_VERSION:
        raise ValueError("batch manifest has an unsupported schema version")
    for key in ("batch_id", "created_at", "input_dir", "output_root", "run_dir"):
        _required_string(data, key, "batch manifest")
    concurrency = data.get("concurrency")
    if not isinstance(concurrency, dict):
        raise ValueError("batch manifest concurrency must be an object")
    _reject_unknown(concurrency, {"visual_workers", "source", "build_workers"}, "concurrency")
    if concurrency.get("source") not in {"requested", "host_config", "default"}:
        raise ValueError("concurrency.source is invalid")
    for key in ("visual_workers", "build_workers"):
        value = concurrency.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"concurrency.{key} must be a positive integer")
    if concurrency["build_workers"] != 1:
        raise ValueError("concurrency.build_workers must be 1")
    papers = data.get("papers")
    if not isinstance(papers, list) or not papers:
        raise ValueError("batch manifest papers must be a non-empty list")
    seen_ids: set[str] = set()
    seen_outputs: set[str] = set()
    for index, paper in enumerate(papers):
        context = f"batch manifest papers[{index}]"
        if not isinstance(paper, dict):
            raise ValueError(f"{context} must be an object")
        paper_allowed = {
            "id",
            "title",
            "output_name",
            "source",
            "workspace",
            "evidence_dir",
            "audit_dir",
            "failed_dir",
        }
        _reject_unknown(paper, paper_allowed, context)
        for key in paper_allowed - {"source"}:
            _required_string(paper, key, context)
        if not _PAPER_ID_RE.fullmatch(paper["id"]):
            raise ValueError(f"{context}.id must match paperNNN")
        if paper["id"] in seen_ids:
            raise ValueError(f"duplicate paper id: {paper['id']}")
        seen_ids.add(paper["id"])
        output_key = paper["output_name"].casefold()
        if output_key in seen_outputs:
            raise ValueError(f"duplicate output filename: {paper['output_name']}")
        seen_outputs.add(output_key)
        source = paper.get("source")
        if not isinstance(source, dict):
            raise ValueError(f"{context}.source must be an object")
        _reject_unknown(source, {"filename", "path", "size", "sha256"}, f"{context}.source")
        _required_string(source, "filename", f"{context}.source")
        _required_string(source, "path", f"{context}.source")
        if isinstance(source.get("size"), bool) or not isinstance(source.get("size"), int) or source["size"] < 0:
            raise ValueError(f"{context}.source.size must be a non-negative integer")
        digest = source.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"{context}.source.sha256 must be a lowercase SHA-256 digest")
    return data


def verify_source_fingerprints(manifest: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for paper in manifest["papers"]:
        source = paper["source"]
        path = Path(source["path"])
        if (
            not path.is_file()
            or path.name != source["filename"]
            or path.stat().st_size != source["size"]
            or sha256_file(path) != source["sha256"]
        ):
            mismatches.append(paper["id"])
    return mismatches


def initial_batch_state(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "batch_id": manifest["batch_id"],
        "papers": {
            paper["id"]: {
                "status": "prepared",
                "attempt": 1,
                "job_path": None,
                "report_path": str(Path(paper["workspace"]) / "pipeline_report.json"),
                "published_pdf": None,
                "archive_path": None,
                "error": None,
                "history": [{"status": "prepared", "attempt": 1}],
            }
            for paper in manifest["papers"]
        },
    }


def load_batch_state(path: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"batch state does not exist: {source}")
    return validate_batch_state(json.loads(source.read_text(encoding="utf-8")), manifest)


def validate_batch_state(data: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("batch state must be an object")
    _reject_unknown(data, {"schema_version", "batch_id", "papers"}, "batch state")
    if data.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError("batch state has an unsupported schema version")
    if data.get("batch_id") != manifest["batch_id"]:
        raise ValueError("batch state batch_id does not match manifest")
    papers = data.get("papers")
    if not isinstance(papers, dict) or set(papers) != {paper["id"] for paper in manifest["papers"]}:
        raise ValueError("batch state paper ids do not match manifest")
    for paper_id, state in papers.items():
        if not isinstance(state, dict):
            raise ValueError(f"batch state {paper_id} must be an object")
        allowed = {
            "status",
            "attempt",
            "job_path",
            "report_path",
            "published_pdf",
            "archive_path",
            "error",
            "history",
        }
        _reject_unknown(state, allowed, f"batch state {paper_id}")
        if state.get("status") not in PAPER_STATUSES:
            raise ValueError(f"batch state {paper_id}.status is invalid")
        attempt = state.get("attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt not in {1, 2}:
            raise ValueError(f"batch state {paper_id}.attempt must be 1 or 2")
        history = state.get("history")
        if not isinstance(history, list) or not history:
            raise ValueError(f"batch state {paper_id}.history must be a non-empty list")
        error = state.get("error")
        if error is not None:
            _validate_error(error, f"batch state {paper_id}.error")
    return data


def write_batch_state(data: dict[str, Any], path: str | Path, manifest: dict[str, Any]) -> Path:
    validated = validate_batch_state(data, manifest)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, validated)
    return destination


def transition_paper(
    state: dict[str, Any],
    paper_id: str,
    status: str,
    *,
    attempt: int | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    paper = state["papers"][paper_id]
    current = paper["status"]
    allowed = {
        "prepared": {"awaiting_ai_layout", "failed"},
        "awaiting_ai_layout": {"ai_layout_running", "failed"},
        "ai_layout_running": {"ai_layout_valid", "awaiting_ai_layout", "failed"},
        "ai_layout_valid": {"building", "failed"},
        "building": {"validated", "failed"},
        "validated": set(),
        "failed": set(),
    }
    if status not in allowed[current]:
        raise ValueError(f"illegal batch transition for {paper_id}: {current} -> {status}")
    if attempt is not None:
        if attempt not in {1, 2}:
            raise ValueError("AI layout attempt must be 1 or 2")
        paper["attempt"] = attempt
    paper["status"] = status
    paper["error"] = safe_error(error_code) if error_code else None
    paper["history"].append({"status": status, "attempt": paper["attempt"]})
    return paper


def make_ai_layout_job(
    manifest: dict[str, Any],
    paper_id: str,
    *,
    attempt: int,
    prompt_path: str | Path,
    outline_path: str | Path,
    skeleton_path: str | Path,
    source_pages_dir: str | Path,
    page_count: int,
) -> dict[str, Any]:
    paper = paper_by_id(manifest, paper_id)
    workspace = Path(paper["workspace"])
    return validate_ai_layout_job(
        {
            "schema_version": JOB_SCHEMA_VERSION,
            "batch_id": manifest["batch_id"],
            "paper_id": paper_id,
            "attempt": attempt,
            "prompt_path": str(Path(prompt_path).resolve()),
            "outline_path": str(Path(outline_path).resolve()),
            "skeleton_path": str(Path(skeleton_path).resolve()),
            "source_pdf": paper["source"]["path"],
            "source_pages_dir": str(Path(source_pages_dir).resolve()),
            "page_count": page_count,
            "allowed_output_path": str((workspace / f"ai_layout.attempt-{attempt}.json").resolve()),
        },
        manifest,
    )


def validate_ai_layout_job(data: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("AI layout job must be an object")
    allowed = {
        "schema_version",
        "batch_id",
        "paper_id",
        "attempt",
        "prompt_path",
        "outline_path",
        "skeleton_path",
        "source_pdf",
        "source_pages_dir",
        "page_count",
        "allowed_output_path",
    }
    _reject_unknown(data, allowed, "AI layout job")
    if data.get("schema_version") != JOB_SCHEMA_VERSION:
        raise ValueError("AI layout job has an unsupported schema version")
    if data.get("batch_id") != manifest["batch_id"]:
        raise ValueError("AI layout job batch_id does not match manifest")
    paper_id = data.get("paper_id")
    paper = paper_by_id(manifest, paper_id)
    attempt = data.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt not in {1, 2}:
        raise ValueError("AI layout job attempt must be 1 or 2")
    for key in (
        "prompt_path",
        "outline_path",
        "skeleton_path",
        "source_pdf",
        "source_pages_dir",
        "allowed_output_path",
    ):
        _required_string(data, key, "AI layout job")
    page_count = data.get("page_count")
    if isinstance(page_count, bool) or not isinstance(page_count, int) or page_count <= 0:
        raise ValueError("AI layout job page_count must be a positive integer")

    workspace = Path(paper["workspace"]).resolve()
    evidence = Path(paper["evidence_dir"]).resolve()
    expected_paths = {
        "outline_path": workspace / "outline.json",
        "skeleton_path": workspace / "ai_layout.skeleton.json",
        "source_pdf": Path(paper["source"]["path"]).resolve(),
        "source_pages_dir": evidence / "source-pages",
        "allowed_output_path": workspace / f"ai_layout.attempt-{attempt}.json",
    }
    for key, expected in expected_paths.items():
        if Path(data[key]).resolve() != expected:
            raise ValueError(f"AI layout job {key} is outside its assigned path")
    prompt = Path(data["prompt_path"]).resolve()
    if prompt.name != "ai_layout_judge.md" or prompt.parent.name != "prompts":
        raise ValueError("AI layout job prompt_path is not the fixed project prompt")
    return data


def write_ai_layout_job(data: dict[str, Any], path: str | Path, manifest: dict[str, Any]) -> Path:
    validated = validate_ai_layout_job(data, manifest)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(destination, validated)
    return destination


def load_ai_layout_job(path: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"AI layout job does not exist: {source}")
    job = validate_ai_layout_job(json.loads(source.read_text(encoding="utf-8")), manifest)
    for key in ("prompt_path", "outline_path", "skeleton_path", "source_pdf"):
        if not Path(job[key]).is_file():
            raise ValueError(f"AI layout job input is missing: {key}")
    source_pages = Path(job["source_pages_dir"])
    if not source_pages.is_dir():
        raise ValueError("AI layout job source_pages_dir is missing")
    expected_names = [f"page-{index:03d}.png" for index in range(1, job["page_count"] + 1)]
    actual_names = [path.name for path in sorted(source_pages.glob("page-*.png"))]
    if actual_names != expected_names:
        raise ValueError("AI layout job source page count or names do not match the job")
    return job


def paper_by_id(manifest: dict[str, Any], paper_id: object) -> dict[str, Any]:
    for paper in manifest["papers"]:
        if paper["id"] == paper_id:
            return paper
    raise ValueError(f"unknown paper id: {paper_id}")


def safe_error(code: str | None) -> dict[str, str] | None:
    if code is None:
        return None
    if not _ERROR_CODE_RE.fullmatch(code):
        raise ValueError("error code must use uppercase letters, digits, and underscores")
    return {"code": code, "message": SAFE_ERROR_MESSAGES.get(code, "The paper stopped with a safe batch error.")}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: str | Path, data: Any) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, destination)
    return destination


def _write_json_exclusive(path: Path, data: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _select_metadata_path(source_dir: Path, metadata_path: str | Path | None) -> Path | None:
    if metadata_path is not None:
        return Path(metadata_path).resolve()
    default = source_dir / "answercard-batch.yaml"
    return default if default.is_file() else None


def _project_temp_root() -> Path:
    return Path(__file__).resolve().parents[2] / ".tmp"


def _run_slug(value: str) -> str:
    slug = _RUN_SLUG_RE.sub("-", value.strip()).strip("-").lower()
    return slug or "batch"


def _append_paper_suffix(filename: str, paper_id: str) -> str:
    return f"{Path(filename).stem}-{paper_id}.pdf"


def _required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value


def _reject_unknown(data: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{context} contains unknown fields: {', '.join(unknown)}")


def _validate_error(data: Any, context: str) -> None:
    if not isinstance(data, dict):
        raise ValueError(f"{context} must be an object")
    _reject_unknown(data, {"code", "message"}, context)
    code = data.get("code")
    message = data.get("message")
    if not isinstance(code, str) or not _ERROR_CODE_RE.fullmatch(code):
        raise ValueError(f"{context}.code is invalid")
    if not isinstance(message, str) or message != safe_error(code)["message"]:
        raise ValueError(f"{context}.message is not the fixed safe message")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
