"""Strict, answer-free prompt-image approval and binding contracts."""

from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import yaml

from answercard.schema import AnswerCardSpec, load_spec
from answercard.visual_requirements import load_visual_requirements


CURRENT_PROMPT_IMAGE_BINDING_SCHEMA_VERSION = 2
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HEIGHT_RE = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d+)?mm$")
_DEFAULT_PLACEMENT = "default"
_HORIZONTAL_REPEAT_PLACEMENT = "horizontal_repeat"
_TOP_RIGHT_PLACEMENT = "top_right"
_BOTTOM_CENTER_PLACEMENT = "bottom_center"
_ASSET_SOURCES = {"cleaned", "approved_original"}


class PromptImageBindingError(ValueError):
    """A safe binding failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, *, item_ids: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.item_ids = item_ids


@dataclass(frozen=True)
class PromptImagePlacement:
    mode: str
    repeat_count: int = 1
    gap_mm: float = 0.0
    height_ratio: float | None = None
    clearance_mm: float = 0.6

    @property
    def total_gap_mm(self) -> float:
        return self.gap_mm * (self.repeat_count - 1)


@dataclass(frozen=True)
class PromptImageBinding:
    id: str
    asset_source: str
    clean_path: Path
    clean_sha256: str
    binding_asset_path: Path
    binding_asset_sha256: str
    placement: PromptImagePlacement
    height_override: str | None = None


@dataclass(frozen=True)
class PromptImageBindingManifest:
    path: Path
    sha256: str
    items: tuple[PromptImageBinding, ...]
    required_item_ids: tuple[str, ...]
    uncertain_item_ids: tuple[str, ...]
    cancelled_visual_item_ids: tuple[str, ...] = ()
    structural_changes: tuple[dict[str, Any], ...] = ()

    @property
    def approved_item_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.items)


def load_prompt_image_binding_manifest(
    manifest_path: str | Path,
    *,
    qspec_path: str | Path,
    visual_requirements_path: str | Path,
) -> PromptImageBindingManifest:
    """Load, strictly validate, and hash-check one whole-paper approval manifest."""

    path = Path(manifest_path)
    try:
        raw_manifest = path.read_bytes()
        data = json.loads(raw_manifest.decode("utf-8"))
    except FileNotFoundError as exc:
        raise PromptImageBindingError(
            "BINDING_MANIFEST_MISSING", f"binding manifest is missing: {path}"
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromptImageBindingError(
            "BINDING_MANIFEST_INVALID", f"binding manifest is not valid JSON: {exc}"
        ) from exc

    spec = load_spec(qspec_path)
    expected_item_ids = _qspec_item_ids(spec)
    visual_requirements = load_visual_requirements(
        visual_requirements_path,
        expected_item_ids=expected_item_ids,
    )
    required_ids, uncertain_ids, allowed_ids = _visual_binding_ids(visual_requirements)
    items, cancelled_ids, structural_changes = _validate_manifest_data(data, base_dir=path.parent)
    approved_ids = {item.id for item in items}

    unknown_cancelled = cancelled_ids - allowed_ids
    if unknown_cancelled:
        raise PromptImageBindingError(
            "BINDING_ITEM_NOT_APPROVABLE",
            "cancelled items must be required or uncertain visual items: " + ", ".join(sorted(unknown_cancelled, key=_id_sort_key)),
            item_ids=tuple(sorted(unknown_cancelled, key=_id_sort_key)),
        )
    missing = tuple(sorted(required_ids - approved_ids - cancelled_ids, key=_id_sort_key))
    if missing:
        raise PromptImageBindingError(
            "WHOLE_PAPER_APPROVAL_INCOMPLETE",
            "all required prompt images must be approved before binding: " + ", ".join(missing),
            item_ids=missing,
        )
    unexpected = tuple(sorted(approved_ids - allowed_ids, key=_id_sort_key))
    if unexpected:
        raise PromptImageBindingError(
            "BINDING_ITEM_NOT_APPROVABLE",
            "binding items must be required or uncertain visual items: " + ", ".join(unexpected),
            item_ids=unexpected,
        )

    for item in items:
        _verify_binding_files(item)

    return PromptImageBindingManifest(
        path=path.resolve(),
        sha256=hashlib.sha256(raw_manifest).hexdigest(),
        items=tuple(items),
        required_item_ids=tuple(sorted(required_ids, key=_id_sort_key)),
        uncertain_item_ids=tuple(sorted(uncertain_ids, key=_id_sort_key)),
        cancelled_visual_item_ids=tuple(sorted(cancelled_ids, key=_id_sort_key)),
        structural_changes=tuple(structural_changes),
    )


def verify_prompt_image_binding_assets(manifest: PromptImageBindingManifest) -> None:
    """Recheck the manifest and every approved file immediately before publication."""

    if not manifest.path.is_file() or sha256_file(manifest.path) != manifest.sha256:
        raise PromptImageBindingError(
            "BINDING_MANIFEST_CHANGED",
            "binding manifest changed after validation; whole-paper reapproval is required",
        )
    for item in manifest.items:
        _verify_binding_files(item)


def write_adjusted_qspec(
    original_qspec_path: str | Path,
    output_path: str | Path,
    manifest: PromptImageBindingManifest,
) -> list[dict[str, str]]:
    """Write an audit qspec copy with approved height overrides, preserving the original."""

    source = Path(original_qspec_path)
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PromptImageBindingError("QSPEC_INVALID", "qspec must be a mapping")
    adjusted = copy.deepcopy(data)
    overrides = {
        item.id: item.height_override
        for item in manifest.items
        if item.height_override is not None
    }
    changes: list[dict[str, str]] = []
    for change in manifest.structural_changes:
        if change["operation"] == "height_override":
            overrides[change["id"]] = change["height"]
        elif change["operation"] == "merge_blocks":
            question = next((q for q in adjusted.get("questions", []) if q.get("id") == change["question_id"]), None)
            if question is None:
                raise PromptImageBindingError("STRUCTURAL_OVERRIDE_INVALID", "merge question id is missing")
            blocks = question.get("blocks", [])
            source_ids = change["source_ids"]
            indices = [i for i, block in enumerate(blocks) if block.get("id") in source_ids]
            if len(indices) != len(source_ids) or sorted(indices) != list(range(min(indices), max(indices) + 1)):
                raise PromptImageBindingError("STRUCTURAL_OVERRIDE_INVALID", "merge source ids must exist contiguously")
            replacement = {"id": change["target_id"], "kind": change["kind"], "height": change["height"]}
            blocks[min(indices):max(indices) + 1] = [replacement]
            changes.append({"operation": "merge_blocks", "from": list(source_ids), "to": change["target_id"]})
    for question in adjusted.get("questions", []):
        if not isinstance(question, dict):
            continue
        for block in question.get("blocks", []):
            if not isinstance(block, dict):
                continue
            item_id = block.get("id")
            if item_id not in overrides:
                continue
            old_height = str(block.get("height"))
            new_height = str(overrides[item_id])
            block["height"] = new_height
            changes.append({"id": str(item_id), "from": old_height, "to": new_height})

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(adjusted, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    load_spec(destination)
    return changes


def write_adjusted_visual_requirements(
    original_path: str | Path,
    output_path: str | Path,
    manifest: PromptImageBindingManifest,
) -> None:
    """Write an answer-free audit copy reflecting cancellations and block merges."""
    data = json.loads(Path(original_path).read_text(encoding="utf-8"))
    cancelled = set(manifest.cancelled_visual_item_ids)
    merges = {source: change["target_id"] for change in manifest.structural_changes if change["operation"] == "merge_blocks" for source in change["source_ids"]}
    for question in data.get("questions", []):
        rewritten = []
        seen = set()
        for item in question.get("items", []):
            item = copy.deepcopy(item)
            item_id = str(item.get("id"))
            if item_id in merges:
                target = merges[item_id]
                if target in seen:
                    continue
                item["id"] = target
                item["visual_requirement"] = "no_visual"
                item["visual_type"] = "none"
                item["requires_preprinted_visual"] = False
                seen.add(target)
            elif item_id in cancelled:
                item["visual_requirement"] = "no_visual"
                item["visual_type"] = "none"
                item["requires_preprinted_visual"] = False
            rewritten.append(item)
        question["items"] = rewritten
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_binding_audit(manifest: PromptImageBindingManifest) -> dict[str, Any]:
    """Return only structured, answer-free placement details for reports."""

    non_default: list[dict[str, Any]] = []
    for item in manifest.items:
        placement = item.placement
        if placement.mode == _DEFAULT_PLACEMENT:
            continue
        non_default.append(
            {
                "id": item.id,
                "mode": placement.mode,
                "repeat_count": placement.repeat_count,
                "gap_mm": placement.gap_mm,
            }
        )
    return {
        "manifest_sha256": manifest.sha256,
        "approved_visual_item_ids": list(manifest.approved_item_ids),
        "cancelled_visual_item_ids": list(manifest.cancelled_visual_item_ids),
        "structural_changes": list(manifest.structural_changes),
        "non_default_placements": non_default,
    }


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_manifest_data(data: Any, *, base_dir: Path) -> tuple[list[PromptImageBinding], set[str], list[dict[str, Any]]]:
    if not isinstance(data, dict):
        raise PromptImageBindingError("BINDING_MANIFEST_INVALID", "binding manifest must be an object")
    _reject_unknown(data, {"schema_version", "approval_scope", "items", "cancelled_visual_item_ids", "structural_changes"}, "manifest")
    version = data.get("schema_version")
    if version not in {1, CURRENT_PROMPT_IMAGE_BINDING_SCHEMA_VERSION}:
        raise PromptImageBindingError(
            "BINDING_MANIFEST_INVALID",
            f"manifest.schema_version must be {CURRENT_PROMPT_IMAGE_BINDING_SCHEMA_VERSION}",
        )
    if data.get("approval_scope") != "whole_paper":
        raise PromptImageBindingError(
            "BINDING_MANIFEST_INVALID", 'manifest.approval_scope must be "whole_paper"'
        )
    raw_items = data.get("items")
    if not isinstance(raw_items, list) or (version == 1 and not raw_items):
        raise PromptImageBindingError(
            "WHOLE_PAPER_APPROVAL_INCOMPLETE", "manifest.items must be a non-empty list"
        )

    items: list[PromptImageBinding] = []
    seen: set[str] = set()
    for index, raw_item in enumerate(raw_items):
        context = f"items[{index}]"
        if not isinstance(raw_item, dict):
            raise PromptImageBindingError("BINDING_MANIFEST_INVALID", f"{context} must be an object")
        allowed = {
                "id", "clean_path", "clean_sha256", "binding_asset_path",
                "binding_asset_sha256", "placement", "height_override",
        }
        if version == 2:
            allowed.add("asset_source")
        _reject_unknown(
            raw_item,
            allowed,
            context,
        )
        item_id = _required_string(raw_item, "id", context)
        if item_id in seen:
            raise PromptImageBindingError(
                "BINDING_MANIFEST_INVALID", f"{context}.id duplicates {item_id}"
            )
        seen.add(item_id)
        asset_source = raw_item.get("asset_source", "cleaned")
        if asset_source not in _ASSET_SOURCES:
            raise PromptImageBindingError("BINDING_MANIFEST_INVALID", f"{context}.asset_source is invalid")
        clean_path = _resolve_asset_path(
            _required_string(raw_item, "clean_path", context), base_dir
        )
        if asset_source == "cleaned" and (clean_path.suffix.lower() != ".png" or not clean_path.stem.lower().endswith("-clean")):
            raise PromptImageBindingError(
                "CLEAN_ASSET_NAME_INVALID",
                f"{context}.clean_path must name a sibling-style <original>-clean.png file",
                item_ids=(item_id,),
            )
        binding_asset_path = _resolve_asset_path(
            _required_string(raw_item, "binding_asset_path", context), base_dir
        )
        if binding_asset_path.suffix.lower() != ".png":
            raise PromptImageBindingError(
                "BINDING_ASSET_INVALID", f"{context}.binding_asset_path must be a PNG"
            )
        clean_hash = _required_sha256(raw_item, "clean_sha256", context)
        binding_hash = _required_sha256(raw_item, "binding_asset_sha256", context)
        placement = _validate_placement(raw_item.get("placement"), context=f"{context}.placement")
        height_override = raw_item.get("height_override")
        if height_override is not None and (
            not isinstance(height_override, str)
            or _HEIGHT_RE.fullmatch(height_override) is None
            or float(height_override[:-2]) <= 0
        ):
            raise PromptImageBindingError(
                "BINDING_MANIFEST_INVALID",
                f'{context}.height_override must be a positive dimension such as "52mm"',
            )
        items.append(
            PromptImageBinding(
                id=item_id,
                asset_source=asset_source,
                clean_path=clean_path,
                clean_sha256=clean_hash,
                binding_asset_path=binding_asset_path,
                binding_asset_sha256=binding_hash,
                placement=placement,
                height_override=height_override,
            )
        )
    cancelled_raw = data.get("cancelled_visual_item_ids", [])
    if not isinstance(cancelled_raw, list) or any(not isinstance(value, str) or not value for value in cancelled_raw):
        raise PromptImageBindingError("BINDING_MANIFEST_INVALID", "manifest.cancelled_visual_item_ids must be a string list")
    cancelled = set(cancelled_raw)
    if len(cancelled) != len(cancelled_raw) or cancelled & seen:
        raise PromptImageBindingError("BINDING_MANIFEST_INVALID", "cancelled ids must be unique and cannot also be bound")
    structural = _validate_structural_changes(data.get("structural_changes", []))
    return items, cancelled, structural


def _validate_placement(data: Any, *, context: str) -> PromptImagePlacement:
    if not isinstance(data, dict):
        raise PromptImageBindingError("BINDING_MANIFEST_INVALID", f"{context} must be an object")
    mode = _required_string(data, "mode", context)
    if mode == _DEFAULT_PLACEMENT:
        _reject_unknown(data, {"mode"}, context)
        return PromptImagePlacement(mode=mode)
    if mode == _HORIZONTAL_REPEAT_PLACEMENT:
        _reject_unknown(data, {"mode", "repeat_count", "gap_mm"}, context)
        repeat_count = data.get("repeat_count")
        if isinstance(repeat_count, bool) or not isinstance(repeat_count, int) or not 2 <= repeat_count <= 12:
            raise PromptImageBindingError(
                "BINDING_MANIFEST_INVALID", f"{context}.repeat_count must be an integer from 2 to 12"
            )
        gap_mm = data.get("gap_mm")
        if isinstance(gap_mm, bool) or not isinstance(gap_mm, (int, float)) or not 0 <= gap_mm <= 50:
            raise PromptImageBindingError(
                "BINDING_MANIFEST_INVALID", f"{context}.gap_mm must be a number from 0 to 50"
            )
        return PromptImagePlacement(mode=mode, repeat_count=repeat_count, gap_mm=float(gap_mm))
    if mode in {_TOP_RIGHT_PLACEMENT, _BOTTOM_CENTER_PLACEMENT}:
        _reject_unknown(data, {"mode", "height_ratio", "clearance_mm"}, context)
        ratio = data.get("height_ratio")
        clearance = data.get("clearance_mm", 0.6)
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 0 < ratio <= 1:
            raise PromptImageBindingError("BINDING_MANIFEST_INVALID", f"{context}.height_ratio must be > 0 and <= 1")
        if isinstance(clearance, bool) or not isinstance(clearance, (int, float)) or clearance < 0.6:
            raise PromptImageBindingError("BINDING_MANIFEST_INVALID", f"{context}.clearance_mm must be at least 0.6")
        return PromptImagePlacement(mode=mode, height_ratio=float(ratio), clearance_mm=float(clearance))
    raise PromptImageBindingError(
        "BINDING_MANIFEST_INVALID",
        f'{context}.mode must be "default", "horizontal_repeat", "top_right", or "bottom_center"',
    )


def _validate_structural_changes(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise PromptImageBindingError("BINDING_MANIFEST_INVALID", "manifest.structural_changes must be a list")
    result = []
    for index, change in enumerate(data):
        context = f"structural_changes[{index}]"
        if not isinstance(change, dict):
            raise PromptImageBindingError("BINDING_MANIFEST_INVALID", f"{context} must be an object")
        operation = change.get("operation")
        if operation == "height_override":
            _reject_unknown(change, {"operation", "id", "height"}, context)
            _required_string(change, "id", context)
            height = _required_string(change, "height", context)
            if _HEIGHT_RE.fullmatch(height) is None or float(height[:-2]) <= 0:
                raise PromptImageBindingError("BINDING_MANIFEST_INVALID", f"{context}.height is invalid")
        elif operation == "merge_blocks":
            _reject_unknown(change, {"operation", "question_id", "source_ids", "target_id", "kind", "height"}, context)
            for key in ("question_id", "target_id", "kind", "height"):
                _required_string(change, key, context)
            sources = change.get("source_ids")
            if not isinstance(sources, list) or len(sources) < 2 or len(set(sources)) != len(sources) or any(not isinstance(value, str) or not value for value in sources):
                raise PromptImageBindingError("BINDING_MANIFEST_INVALID", f"{context}.source_ids must contain unique ids")
            if _HEIGHT_RE.fullmatch(change["height"]) is None or float(change["height"][:-2]) <= 0:
                raise PromptImageBindingError("BINDING_MANIFEST_INVALID", f"{context}.height is invalid")
        else:
            raise PromptImageBindingError("BINDING_MANIFEST_INVALID", f"{context}.operation is invalid")
        result.append(copy.deepcopy(change))
    return result


def _verify_binding_files(item: PromptImageBinding) -> None:
    for role, path, expected_hash in (
        ("clean", item.clean_path, item.clean_sha256),
        ("binding", item.binding_asset_path, item.binding_asset_sha256),
    ):
        if not path.is_file():
            raise PromptImageBindingError(
                "BINDING_ASSET_MISSING",
                f"approved {role} asset is missing for {item.id}: {path}",
                item_ids=(item.id,),
            )
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise PromptImageBindingError(
                "CLEAN_HASH_CHANGED" if role == "clean" else "BINDING_ASSET_HASH_CHANGED",
                f"approved {role} asset hash changed for {item.id}; whole-paper reapproval is required",
                item_ids=(item.id,),
            )


def _qspec_item_ids(spec: AnswerCardSpec) -> list[str]:
    return [block.id for question in spec.questions for block in question.blocks]


def _visual_binding_ids(data: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    required: set[str] = set()
    uncertain: set[str] = set()
    for question in data["questions"]:
        for item in question["items"]:
            item_id = str(item["id"])
            if item["requires_preprinted_visual"] is True:
                required.add(item_id)
            elif item["visual_requirement"] == "uncertain":
                uncertain.add(item_id)
    return required, uncertain, required | uncertain


def _resolve_asset_path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise PromptImageBindingError("BINDING_MANIFEST_INVALID", f"{context}.{key} must be a non-empty string")
    return value


def _required_sha256(data: dict[str, Any], key: str, context: str) -> str:
    value = _required_string(data, key, context)
    if _SHA256_RE.fullmatch(value) is None:
        raise PromptImageBindingError(
            "BINDING_MANIFEST_INVALID", f"{context}.{key} must be a lowercase SHA-256"
        )
    return value


def _reject_unknown(data: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise PromptImageBindingError(
            "BINDING_MANIFEST_INVALID",
            f"{context} contains unsupported field(s): {', '.join(unknown)}",
        )


def _id_sort_key(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("-"))
    except ValueError:
        return (10**9,)
