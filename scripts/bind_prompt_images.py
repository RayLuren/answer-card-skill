from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from answercard.frame_alignment import (  # noqa: E402
    DEFAULT_ALIGNMENT_TOLERANCE_MM,
    DEFAULT_MAX_ALIGNMENT_PASSES,
)
from answercard.prompt_image_binding import (  # noqa: E402
    PromptImageBindingError,
    PromptImageBindingManifest,
    load_prompt_image_binding_manifest,
    render_binding_audit,
    sha256_file,
    verify_prompt_image_binding_assets,
    write_adjusted_qspec,
    write_adjusted_visual_requirements,
)
from answercard.pipeline_timing import PipelineTimer  # noqa: E402
from answercard.schema import load_spec  # noqa: E402
from answercard.task_report import write_task_report  # noqa: E402
from answercard.visual_requirements import load_visual_requirements, visual_item_machine_id  # noqa: E402
from build import BuildError, build_answer_card  # noqa: E402
from finalize_pipeline import FinalizePipelineError, finalize_pipeline  # noqa: E402
from render_pages import RenderPagesError, render_pdf_pages  # noqa: E402


DEFAULT_QSPEC = PROJECT_ROOT / "spec" / "qspec.draft.yaml"
DEFAULT_BUILD_DIR = PROJECT_ROOT / "build"
DEFAULT_VISUAL_REQUIREMENTS = DEFAULT_BUILD_DIR / "visual_requirements.json"
DEFAULT_PIPELINE_REPORT = DEFAULT_BUILD_DIR / "pipeline_report.json"
DEFAULT_FORMAL_PDF = DEFAULT_BUILD_DIR / "answercard.pdf"
DEFAULT_TEMP_ROOT = PROJECT_ROOT / ".tmp"


class PromptImageBindingPipelineError(RuntimeError):
    """A user-facing whole-paper binding or publication failure."""


def bind_prompt_images(
    manifest_path: str | Path,
    *,
    qspec_path: str | Path = DEFAULT_QSPEC,
    visual_requirements_path: str | Path = DEFAULT_VISUAL_REQUIREMENTS,
    build_dir: str | Path = DEFAULT_BUILD_DIR,
    formal_pdf_path: str | Path = DEFAULT_FORMAL_PDF,
    pipeline_report_path: str | Path = DEFAULT_PIPELINE_REPORT,
    task_report_path: str | Path | None = None,
    temp_root: str | Path = DEFAULT_TEMP_ROOT,
    xelatex: str = "xelatex",
    alignment_tolerance_mm: float = DEFAULT_ALIGNMENT_TOLERANCE_MM,
    max_alignment_passes: int = DEFAULT_MAX_ALIGNMENT_PASSES,
) -> dict[str, Any]:
    """Bind one fully approved paper in isolation, validate it, then publish atomically."""

    qspec = Path(qspec_path)
    visual_requirements = Path(visual_requirements_path)
    formal_build = Path(build_dir)
    formal_pdf = Path(formal_pdf_path)
    formal_report = Path(pipeline_report_path)
    task_report = Path(task_report_path) if task_report_path is not None else None
    temp = Path(temp_root)
    temp.mkdir(parents=True, exist_ok=True)

    manifest: PromptImageBindingManifest | None = None
    staging: Path | None = None
    approved_ids: list[str] = []
    pending_ids = _required_visual_ids(qspec, visual_requirements)
    phase = "approval"

    try:
        manifest = load_prompt_image_binding_manifest(
            manifest_path,
            qspec_path=qspec,
            visual_requirements_path=visual_requirements,
        )
        approved_ids = list(manifest.approved_item_ids)
        pending_ids = [item_id for item_id in manifest.required_item_ids if item_id not in approved_ids]

        phase = "build"
        staging = temp / f"prompt-image-binding-{uuid4().hex}"
        staging.mkdir(parents=True)
        staged_qspec = staging / "qspec.binding.yaml"
        staged_visual = staging / "visual_requirements.json"
        staged_report = staging / "pipeline_report.json"
        staged_manifest = staging / "prompt_image_binding.json"
        staged_ai_paper: Path | None = None
        staged_assets = staging / "binding-assets"
        staged_assets.mkdir()

        if formal_report.is_file():
            shutil.copy2(formal_report, staged_report)
        else:
            raise PromptImageBindingError(
                "PIPELINE_REPORT_MISSING", f"pipeline report is missing: {formal_report}"
            )
        shutil.copy2(manifest.path, staged_manifest)
        input_spec = load_spec(qspec)
        if input_spec.schema_version == 2:
            formal_ai_paper = formal_build / "ai_paper_spec.json"
            if not formal_ai_paper.is_file():
                raise PromptImageBindingError(
                    "AI_PAPER_SPEC_MISSING", f"whole-paper visual AI spec is missing: {formal_ai_paper}"
                )
            staged_ai_paper = staging / "ai_paper_spec.json"
            shutil.copy2(formal_ai_paper, staged_ai_paper)
        height_overrides = write_adjusted_qspec(qspec, staged_qspec, manifest)
        write_adjusted_visual_requirements(visual_requirements, staged_visual, manifest)
        render_bindings = _stage_binding_assets(manifest, staged_assets)
        if not manifest.items and not manifest.structural_changes:
            phase = "publish"
            binding_result = {
                "status": "cancelled",
                "pending_visual_item_ids": [],
                **render_binding_audit(manifest),
                "embedded_visual_item_ids": [],
                "failed_visual_item_ids": [],
                "height_overrides": [],
                "adjusted_qspec": "qspec.binding.yaml",
                "adjusted_visual_requirements": "visual_requirements.binding.json",
                "published_pdf_sha256": sha256_file(formal_pdf),
                "pdf_rewritten": False,
            }
            _update_staged_report(staged_report, binding_result)
            _publish_audit_only_binding(
                staging=staging,
                formal_build=formal_build,
                formal_report=formal_report,
            )
            shutil.rmtree(staging)
            return binding_result
        timer = PipelineTimer(staged_report)
        timer.ensure_running(reset_if_finished=False)
        timer.update_configuration(
            {
                "alignment_tolerance_mm": alignment_tolerance_mm,
                "default_alignment_tolerance_mm": DEFAULT_ALIGNMENT_TOLERANCE_MM,
                "max_alignment_passes": max_alignment_passes,
                "default_max_alignment_passes": DEFAULT_MAX_ALIGNMENT_PASSES,
            }
        )
        timer.run(
            "bind_prompt_images_build",
            build_answer_card,
            staged_qspec,
            build_dir=staging,
            xelatex=xelatex,
            align_pages=True,
            max_alignment_passes=max_alignment_passes,
            alignment_tolerance_mm=alignment_tolerance_mm,
            image_bindings=render_bindings,
        )
        timer.run(
            "bind_prompt_images_render_pages",
            render_pdf_pages,
            staging / "answercard.pdf",
            staging / "pages",
        )
        spec = load_spec(staged_qspec)
        finalize_pipeline(
            ai_paper_path=staged_ai_paper,
            qspec_path=staged_qspec,
            pdf_path=staging / "answercard.pdf",
            pages_dir=staging / "pages",
            build_dir=staging,
            alignment_report_path=staging / "frame_alignment.json",
            visual_requirements_path=staged_visual,
            report_path=staged_report,
            log_paths=(staging / "answercard.log",),
            front_pages=0 if spec.paper.omit_front_page else 1,
            alignment_tolerance_mm=alignment_tolerance_mm,
            temp_root=temp,
        )

        verify_prompt_image_binding_assets(manifest)
        validated_pdf_hash = sha256_file(staging / "answercard.pdf")
        binding_result = {
            "status": "embedded",
            "pending_visual_item_ids": [],
            **render_binding_audit(manifest),
            "embedded_visual_item_ids": approved_ids,
            "failed_visual_item_ids": [],
            "height_overrides": height_overrides,
            "adjusted_qspec": "qspec.binding.yaml",
            "published_pdf_sha256": validated_pdf_hash,
        }
        _update_staged_report(staged_report, binding_result)

        phase = "publish"
        _publish_validated_binding(
            staging=staging,
            formal_build=formal_build,
            formal_pdf=formal_pdf,
            formal_report=formal_report,
            task_report=task_report,
            expected_pdf_sha256=validated_pdf_hash,
        )

        shutil.rmtree(staging)
        return binding_result
    except Exception as exc:
        code = _failure_code(exc, phase=phase)
        failed_ids = approved_ids or list(getattr(exc, "item_ids", ()))
        diagnostic_path = _retain_failure_diagnostics(
            staging,
            formal_build=formal_build,
            code=code,
            item_ids=failed_ids,
        )
        failure_result = {
            "status": "failed",
            "failure_code": code,
            "pending_visual_item_ids": pending_ids,
            "approved_visual_item_ids": approved_ids,
            "embedded_visual_item_ids": [],
            "failed_visual_item_ids": failed_ids,
            "diagnostic_path": str(diagnostic_path),
        }
        _record_formal_binding_result(formal_report, failure_result)
        if task_report is not None and formal_report.is_file():
            write_task_report([formal_report], task_report)
        raise PromptImageBindingPipelineError(f"{code}: {exc}") from exc


def check_prompt_image_binding(
    manifest_path: str | Path,
    *,
    qspec_path: str | Path = DEFAULT_QSPEC,
    visual_requirements_path: str | Path = DEFAULT_VISUAL_REQUIREMENTS,
) -> PromptImageBindingManifest:
    """Run the approval/hash gate without modifying any formal artifact."""

    return load_prompt_image_binding_manifest(
        manifest_path,
        qspec_path=qspec_path,
        visual_requirements_path=visual_requirements_path,
    )


def _stage_binding_assets(
    manifest: PromptImageBindingManifest,
    destination: Path,
) -> dict[str, dict[str, Any]]:
    bindings: dict[str, dict[str, Any]] = {}
    for item in manifest.items:
        asset_name = f"{item.id}.png"
        staged_asset = destination / asset_name
        shutil.copy2(item.binding_asset_path, staged_asset)
        if sha256_file(staged_asset) != item.binding_asset_sha256:
            raise PromptImageBindingError(
                "STAGED_ASSET_HASH_MISMATCH",
                f"staged binding asset hash mismatch for {item.id}",
                item_ids=(item.id,),
            )
        placement = item.placement
        bindings[item.id] = {
            "mode": placement.mode,
            "repeat_count": placement.repeat_count,
            "gap_mm": _compact_number(placement.gap_mm),
            "total_gap_mm": _compact_number(placement.total_gap_mm),
            "height_ratio": placement.height_ratio,
            "clearance_mm": _compact_number(placement.clearance_mm),
            "asset_path": f"binding-assets/{asset_name}",
        }
    return bindings


def _publish_validated_binding(
    *,
    staging: Path,
    formal_build: Path,
    formal_pdf: Path,
    formal_report: Path,
    task_report: Path | None,
    expected_pdf_sha256: str,
) -> None:
    formal_build.mkdir(parents=True, exist_ok=True)
    rollback_dir = staging / ".rollback"
    rollback_dir.mkdir()
    pdf_existed = formal_pdf.is_file()
    report_existed = formal_report.is_file()
    task_report_existed = task_report.is_file() if task_report is not None else False
    if pdf_existed:
        shutil.copy2(formal_pdf, rollback_dir / "formal.pdf")
    if report_existed:
        shutil.copy2(formal_report, rollback_dir / "pipeline_report.json")
    if task_report_existed and task_report is not None:
        shutil.copy2(task_report, rollback_dir / "task-report.md")

    pdf_replaced = False
    report_replaced = False
    task_report_replaced = False
    try:
        for name in (
            "answercard.tex",
            "answercard.log",
            "frame_alignment.json",
            "qspec.binding.yaml",
            "prompt_image_binding.json",
        ):
            _atomic_copy(staging / name, formal_build / name)
        _atomic_copy(staging / "visual_requirements.json", formal_build / "visual_requirements.binding.json")
        _publish_directory(staging / "binding-assets", formal_build / "binding-assets")
        _publish_directory(staging / "pages", formal_build / "pages")

        _atomic_copy(staging / "answercard.pdf", formal_pdf)
        pdf_replaced = True
        if sha256_file(formal_pdf) != expected_pdf_sha256:
            raise PromptImageBindingError(
                "PUBLISHED_PDF_HASH_MISMATCH",
                "published PDF hash does not match the validated binding artifact",
            )
        _atomic_copy(staging / "pipeline_report.json", formal_report)
        report_replaced = True
        if task_report is not None:
            write_task_report([formal_report], staging / "task-report.md")
            _atomic_copy(staging / "task-report.md", task_report)
            task_report_replaced = True
    except Exception:
        if task_report is not None and task_report_replaced:
            _restore_or_remove(
                task_report,
                rollback_dir / "task-report.md",
                existed=task_report_existed,
            )
        if report_replaced:
            _restore_or_remove(
                formal_report,
                rollback_dir / "pipeline_report.json",
                existed=report_existed,
            )
        if pdf_replaced:
            _restore_or_remove(formal_pdf, rollback_dir / "formal.pdf", existed=pdf_existed)
        raise


def _publish_audit_only_binding(*, staging: Path, formal_build: Path, formal_report: Path) -> None:
    """Publish cancellation audit artifacts without touching the formal PDF."""
    formal_build.mkdir(parents=True, exist_ok=True)
    report_backup = staging / ".pipeline-report.rollback.json"
    report_existed = formal_report.is_file()
    if report_existed:
        shutil.copy2(formal_report, report_backup)
    try:
        _atomic_copy(staging / "qspec.binding.yaml", formal_build / "qspec.binding.yaml")
        _atomic_copy(staging / "visual_requirements.json", formal_build / "visual_requirements.binding.json")
        _atomic_copy(staging / "prompt_image_binding.json", formal_build / "prompt_image_binding.json")
        _atomic_copy(staging / "pipeline_report.json", formal_report)
    except Exception:
        _restore_or_remove(formal_report, report_backup, existed=report_existed)
        raise


def _publish_directory(source: Path, destination: Path) -> None:
    temporary = destination.with_name(destination.name + f".tmp-{uuid4().hex}")
    shutil.copytree(source, temporary)
    if destination.exists():
        shutil.rmtree(destination)
    temporary.replace(destination)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".tmp-{uuid4().hex}")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def _restore_or_remove(target: Path, backup: Path, *, existed: bool) -> None:
    if existed:
        _atomic_copy(backup, target)
    else:
        target.unlink(missing_ok=True)


def _update_staged_report(path: Path, binding_result: dict[str, Any]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    result = data.setdefault("result", {})
    if not isinstance(result, dict):
        raise ValueError("pipeline report result must be an object")
    result["prompt_image_binding"] = binding_result
    result["embedded_visual_item_ids"] = binding_result["embedded_visual_item_ids"]
    result["visual_asset_status"] = binding_result["status"]
    _atomic_write_json(path, data)


def _record_formal_binding_result(path: Path, binding_result: dict[str, Any]) -> None:
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        result = data.setdefault("result", {})
        if not isinstance(result, dict):
            return
        result["prompt_image_binding"] = binding_result
        _atomic_write_json(path, data)
    except (OSError, ValueError, json.JSONDecodeError):
        return


def _atomic_write_json(path: Path, data: Any) -> None:
    temporary = path.with_name(path.name + f".tmp-{uuid4().hex}")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _required_visual_ids(qspec_path: Path, visual_path: Path) -> list[str]:
    try:
        spec = load_spec(qspec_path)
        item_ids = [block.id for question in spec.questions for block in question.blocks]
        data = load_visual_requirements(visual_path, expected_item_ids=item_ids)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    return [
        visual_item_machine_id(item)
        for question in data["questions"]
        for item in question["items"]
        if item["requires_preprinted_visual"] is True
    ]


def _retain_failure_diagnostics(
    staging: Path | None,
    *,
    formal_build: Path,
    code: str,
    item_ids: list[str],
) -> Path:
    failure_root = formal_build / "binding-failures"
    failure_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = failure_root / f"{stamp}-{uuid4().hex[:8]}"
    if staging is not None and staging.exists():
        shutil.move(str(staging), destination)
    else:
        destination.mkdir()
    _atomic_write_json(
        destination / "binding_failure.json",
        {"failure_code": code, "item_ids": item_ids},
    )
    return destination


def _failure_code(exc: Exception, *, phase: str) -> str:
    if isinstance(exc, PromptImageBindingError):
        return exc.code
    if isinstance(exc, BuildError):
        return "BINDING_BUILD_FAILED"
    if isinstance(exc, RenderPagesError):
        return "BINDING_PREVIEW_FAILED"
    if isinstance(exc, FinalizePipelineError):
        return "BINDING_VALIDATION_FAILED"
    return "BINDING_PUBLISH_FAILED" if phase == "publish" else "BINDING_FAILED"


def _compact_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate or apply one whole-paper approved prompt-image binding manifest."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Validate approval coverage and asset hashes only.")
    _add_common_arguments(check)

    bind = subparsers.add_parser("bind", help="Rebuild, validate, and atomically publish one paper.")
    _add_common_arguments(bind)
    bind.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR)
    bind.add_argument("--formal-pdf", type=Path, default=DEFAULT_FORMAL_PDF)
    bind.add_argument("--pipeline-report", type=Path, default=DEFAULT_PIPELINE_REPORT)
    bind.add_argument("--task-report", type=Path)
    bind.add_argument("--temp-root", type=Path, default=DEFAULT_TEMP_ROOT)
    bind.add_argument("--xelatex", default="xelatex")
    bind.add_argument(
        "--alignment-tolerance-mm", type=float, default=DEFAULT_ALIGNMENT_TOLERANCE_MM
    )
    bind.add_argument("--max-alignment-passes", type=int, default=DEFAULT_MAX_ALIGNMENT_PASSES)
    args = parser.parse_args(argv)

    try:
        if args.command == "check":
            manifest = check_prompt_image_binding(
                args.manifest,
                qspec_path=args.qspec,
                visual_requirements_path=args.visual_requirements,
            )
            print("approved_item_ids: " + ", ".join(manifest.approved_item_ids))
            return 0
        result = bind_prompt_images(
            args.manifest,
            qspec_path=args.qspec,
            visual_requirements_path=args.visual_requirements,
            build_dir=args.build_dir,
            formal_pdf_path=args.formal_pdf,
            pipeline_report_path=args.pipeline_report,
            task_report_path=args.task_report,
            temp_root=args.temp_root,
            xelatex=args.xelatex,
            alignment_tolerance_mm=args.alignment_tolerance_mm,
            max_alignment_passes=args.max_alignment_passes,
        )
    except (PromptImageBindingPipelineError, PromptImageBindingError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("embedded_item_ids: " + ", ".join(result["embedded_visual_item_ids"]))
    print(f"formal_pdf: {args.formal_pdf}")
    return 0


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--qspec", type=Path, default=DEFAULT_QSPEC)
    parser.add_argument(
        "--visual-requirements", type=Path, default=DEFAULT_VISUAL_REQUIREMENTS
    )


if __name__ == "__main__":
    raise SystemExit(main())
