"""Answer-free visual requirement manifests for legacy and qspec-v2 paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from answercard.ai_paper_schema import (
    ALLOWED_VISUAL_REQUIREMENTS,
    ALLOWED_VISUAL_TYPES,
    PREPRINTED_VISUAL_REQUIREMENTS,
)
from answercard.ai_paper_schema import READY, load_ai_paper_spec


CURRENT_VISUAL_REQUIREMENTS_SCHEMA_VERSION = 2
SUPPORTED_VISUAL_REQUIREMENTS_SCHEMA_VERSIONS = {1, 2}


def export_visual_requirements(
    source_path: str | Path,
    output_path: str | Path,
    *,
    page_count: int | None = None,
) -> Path:
    """Write visual decisions from ai_paper_spec (v2) or legacy ai_layout (v1)."""

    if page_count is None:
        raise ValueError("page_count is required for ai_paper_spec visual export")
    source = load_ai_paper_spec(source_path, page_count=page_count)
    manifest = build_visual_requirements(source)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def build_visual_requirements(source: dict[str, Any]) -> dict[str, Any]:
    if source.get("status") == READY:
        questions: list[dict[str, Any]] = []
        for question_index, question in enumerate(source["questions"], start=1):
            question_id = f"q{question_index:03d}"
            items = []
            for item_index, item in enumerate(question["items"], start=1):
                requirement = item["visual_requirement"]
                items.append(
                    {
                        "item_id": f"{question_id}-i{item_index:03d}",
                        "display_id": item["number"],
                        "visual_requirement": requirement,
                        "visual_type": item["visual_type"],
                        "requires_preprinted_visual": _preprinted_value(requirement),
                    }
                )
            questions.append(
                {"question_id": question_id, "display_id": question["number"], "items": items}
            )
        return validate_visual_requirements({"schema_version": 2, "questions": questions})

    raise ValueError("visual requirements may be exported only from status ready ai_paper_spec")


def load_visual_requirements(
    path: str | Path,
    *,
    expected_item_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_visual_requirements(data, expected_item_ids=expected_item_ids)


def validate_visual_requirements(
    data: Any,
    *,
    expected_item_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("visual requirements must be a JSON object")
    _reject_unknown(data, {"schema_version", "questions"}, "visual_requirements")
    version = data.get("schema_version")
    if version not in SUPPORTED_VISUAL_REQUIREMENTS_SCHEMA_VERSIONS:
        raise ValueError("visual_requirements.schema_version must be 1 or 2")
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("visual_requirements.questions must be a non-empty list")

    seen_questions: set[str] = set()
    seen_items: set[str] = set()
    for question_index, question in enumerate(questions):
        context = f"questions[{question_index}]"
        if not isinstance(question, dict):
            raise ValueError(f"{context} must be an object")
        if version == 1:
            _reject_unknown(question, {"id", "items"}, context)
            question_id = _required_str(question, "id", context)
        else:
            _reject_unknown(question, {"question_id", "display_id", "items"}, context)
            question_id = _required_str(question, "question_id", context)
            _required_str(question, "display_id", context)
        if question_id in seen_questions:
            raise ValueError(f"{context} machine id duplicates {question_id}")
        seen_questions.add(question_id)
        items = question.get("items")
        if not isinstance(items, list):
            raise ValueError(f"{context}.items must be a list")
        for item_index, item in enumerate(items):
            item_context = f"{context}.items[{item_index}]"
            if not isinstance(item, dict):
                raise ValueError(f"{item_context} must be an object")
            common = {"visual_requirement", "visual_type", "requires_preprinted_visual"}
            if version == 1:
                _reject_unknown(item, common | {"id"}, item_context)
                item_id = _required_str(item, "id", item_context)
            else:
                _reject_unknown(item, common | {"item_id", "display_id"}, item_context)
                item_id = _required_str(item, "item_id", item_context)
                _required_str(item, "display_id", item_context)
            if item_id in seen_items:
                raise ValueError(f"{item_context} machine id duplicates {item_id}")
            seen_items.add(item_id)
            if item_id != question_id and not item_id.startswith(f"{question_id}-"):
                raise ValueError(f"{item_context} machine id must belong to {question_id}")
            requirement = _required_str(item, "visual_requirement", item_context)
            if requirement not in ALLOWED_VISUAL_REQUIREMENTS:
                raise ValueError(f"{item_context}.visual_requirement is invalid")
            visual_type = _required_str(item, "visual_type", item_context)
            if visual_type not in ALLOWED_VISUAL_TYPES:
                raise ValueError(f"{item_context}.visual_type is invalid")
            _validate_visual_combination(requirement, visual_type, context=item_context)
            if item.get("requires_preprinted_visual") is not _preprinted_value(requirement):
                raise ValueError(f"{item_context}.requires_preprinted_visual is inconsistent")
    if expected_item_ids is not None:
        expected = {str(item_id) for item_id in expected_item_ids}
        missing = sorted(expected - seen_items)
        extra = sorted(seen_items - expected)
        if missing or extra:
            raise ValueError(f"visual requirements item coverage mismatch (missing={missing}; extra={extra})")
    return data


def visual_item_machine_id(item: dict[str, Any]) -> str:
    return str(item.get("item_id", item.get("id")))


def visual_item_display_id(item: dict[str, Any]) -> str:
    return str(item.get("display_id", visual_item_machine_id(item)))


def visual_requirement_counts(data: dict[str, Any]) -> dict[str, int]:
    counts = {requirement: 0 for requirement in sorted(ALLOWED_VISUAL_REQUIREMENTS)}
    for question in data["questions"]:
        for item in question["items"]:
            counts[item["visual_requirement"]] += 1
    return counts


def visual_requirement_report_data(data: dict[str, Any]) -> dict[str, Any]:
    preprinted_items: list[dict[str, Any]] = []
    uncertain_items: list[dict[str, Any]] = []
    for question in data["questions"]:
        for item in question["items"]:
            entry = {
                "id": visual_item_machine_id(item),
                "display_id": visual_item_display_id(item),
                "visual_requirement": item["visual_requirement"],
                "visual_type": item["visual_type"],
            }
            if item["requires_preprinted_visual"] is True:
                preprinted_items.append(entry)
            elif item["visual_requirement"] == "uncertain":
                uncertain_items.append(entry)
    status = "awaiting_manual_assets" if preprinted_items else (
        "visual_review_required" if uncertain_items else "not_required"
    )
    return {
        "preprinted_visual_items": preprinted_items,
        "uncertain_visual_items": uncertain_items,
        "visual_asset_status": status,
    }


def _preprinted_value(requirement: str) -> bool | None:
    if requirement == "uncertain":
        return None
    return requirement in PREPRINTED_VISUAL_REQUIREMENTS


def _validate_visual_combination(requirement: str, visual_type: str, *, context: str) -> None:
    if requirement == "no_visual" and visual_type != "none":
        raise ValueError(f'{context}.visual_type must be "none" for no_visual')
    if requirement == "uncertain" and visual_type != "uncertain":
        raise ValueError(f'{context}.visual_type must be "uncertain" for uncertain')
    if requirement not in {"no_visual", "uncertain"} and visual_type in {"none", "uncertain"}:
        raise ValueError(f"{context}.visual_type must identify the visual")


def _reject_unknown(data: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{context} contains unknown field(s): {', '.join(unknown)}")


def _required_str(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value
