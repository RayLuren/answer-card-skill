"""Answer-free visual-requirement manifests derived from validated AI layout data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from answercard.ai_layout_schema import (
    ALLOWED_VISUAL_REQUIREMENTS,
    ALLOWED_VISUAL_TYPES,
    PREPRINTED_VISUAL_REQUIREMENTS,
    load_ai_layout,
)


CURRENT_VISUAL_REQUIREMENTS_SCHEMA_VERSION = 1


def export_visual_requirements(
    ai_layout_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Validate AI layout data and write its structure-only visual decisions."""

    manifest = build_visual_requirements(load_ai_layout(ai_layout_path))
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def build_visual_requirements(ai_layout: dict[str, Any]) -> dict[str, Any]:
    """Project visual fields from already validated AI layout data."""

    questions: list[dict[str, Any]] = []
    for question in ai_layout["questions"]:
        items = []
        for item in question["items"]:
            requirement = item["visual_requirement"]
            items.append(
                {
                    "id": item["id"],
                    "visual_requirement": requirement,
                    "visual_type": item["visual_type"],
                    "requires_preprinted_visual": _preprinted_value(requirement),
                }
            )
        questions.append({"id": question["id"], "items": items})

    manifest = {
        "schema_version": CURRENT_VISUAL_REQUIREMENTS_SCHEMA_VERSION,
        "questions": questions,
    }
    return validate_visual_requirements(manifest)


def load_visual_requirements(
    path: str | Path,
    *,
    expected_item_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as manifest_file:
        data = json.load(manifest_file)
    return validate_visual_requirements(data, expected_item_ids=expected_item_ids)


def validate_visual_requirements(
    data: Any,
    *,
    expected_item_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("visual requirements must be a JSON object")
    _reject_unknown_fields(data, {"schema_version", "questions"}, "visual_requirements")
    if data.get("schema_version") != CURRENT_VISUAL_REQUIREMENTS_SCHEMA_VERSION:
        raise ValueError(
            "visual_requirements.schema_version must be "
            f"{CURRENT_VISUAL_REQUIREMENTS_SCHEMA_VERSION}"
        )

    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("visual_requirements.questions must be a non-empty list")

    seen_questions: set[str] = set()
    seen_items: set[str] = set()
    for question_index, question in enumerate(questions):
        context = f"questions[{question_index}]"
        if not isinstance(question, dict):
            raise ValueError(f"{context} must be an object")
        _reject_unknown_fields(question, {"id", "items"}, context)
        question_id = _required_str(question, "id", context)
        if question_id in seen_questions:
            raise ValueError(f"{context}.id duplicates {question_id}")
        seen_questions.add(question_id)
        items = question.get("items")
        if not isinstance(items, list):
            raise ValueError(f"{context}.items must be a list")
        for item_index, item in enumerate(items):
            item_context = f"{context}.items[{item_index}]"
            if not isinstance(item, dict):
                raise ValueError(f"{item_context} must be an object")
            _reject_unknown_fields(
                item,
                {
                    "id",
                    "visual_requirement",
                    "visual_type",
                    "requires_preprinted_visual",
                },
                item_context,
            )
            item_id = _required_str(item, "id", item_context)
            if item_id in seen_items:
                raise ValueError(f"{item_context}.id duplicates {item_id}")
            seen_items.add(item_id)
            if item_id != question_id and not item_id.startswith(f"{question_id}-"):
                raise ValueError(f"{item_context}.id must belong to question {question_id}")

            requirement = _required_str(item, "visual_requirement", item_context)
            if requirement not in ALLOWED_VISUAL_REQUIREMENTS:
                raise ValueError(f"{item_context}.visual_requirement must be an allowed visual requirement")
            visual_type = _required_str(item, "visual_type", item_context)
            if visual_type not in ALLOWED_VISUAL_TYPES:
                raise ValueError(f"{item_context}.visual_type must be an allowed visual type")
            _validate_visual_combination(requirement, visual_type, context=item_context)

            expected_preprinted = _preprinted_value(requirement)
            if item.get("requires_preprinted_visual") is not expected_preprinted:
                raise ValueError(
                    f"{item_context}.requires_preprinted_visual is inconsistent with visual_requirement"
                )

    if expected_item_ids is not None:
        expected = {str(item_id) for item_id in expected_item_ids}
        missing = sorted(expected - seen_items)
        extra = sorted(seen_items - expected)
        if missing or extra:
            details = []
            if missing:
                details.append("missing: " + ", ".join(missing))
            if extra:
                details.append("extra: " + ", ".join(extra))
            raise ValueError("visual requirements item coverage mismatch (" + "; ".join(details) + ")")

    return data


def visual_requirement_counts(data: dict[str, Any]) -> dict[str, int]:
    counts = {requirement: 0 for requirement in sorted(ALLOWED_VISUAL_REQUIREMENTS)}
    for question in data["questions"]:
        for item in question["items"]:
            counts[item["visual_requirement"]] += 1
    return counts


def visual_requirement_report_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return answer-free item details required by the user-facing task report."""

    preprinted_items: list[dict[str, Any]] = []
    uncertain_items: list[dict[str, Any]] = []
    for question in data["questions"]:
        for item in question["items"]:
            entry = {
                "id": item["id"],
                "visual_requirement": item["visual_requirement"],
                "visual_type": item["visual_type"],
            }
            if item["requires_preprinted_visual"] is True:
                preprinted_items.append(entry)
            elif item["visual_requirement"] == "uncertain":
                uncertain_items.append(entry)

    if preprinted_items:
        asset_status = "awaiting_manual_assets"
    elif uncertain_items:
        asset_status = "visual_review_required"
    else:
        asset_status = "not_required"
    return {
        "preprinted_visual_items": preprinted_items,
        "uncertain_visual_items": uncertain_items,
        "visual_asset_status": asset_status,
    }


def _preprinted_value(requirement: str) -> bool | None:
    if requirement == "uncertain":
        return None
    return requirement in PREPRINTED_VISUAL_REQUIREMENTS


def _validate_visual_combination(requirement: str, visual_type: str, *, context: str) -> None:
    if requirement == "no_visual" and visual_type != "none":
        raise ValueError(f'{context}.visual_type must be "none" when visual_requirement is "no_visual"')
    if requirement == "uncertain" and visual_type != "uncertain":
        raise ValueError(f'{context}.visual_type must be "uncertain" when visual_requirement is "uncertain"')
    if requirement not in {"no_visual", "uncertain"} and visual_type in {"none", "uncertain"}:
        raise ValueError(
            f"{context}.visual_type must identify the visual when visual_requirement is {requirement}"
        )


def _reject_unknown_fields(data: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{context} contains unknown field(s): {', '.join(unknown)}")


def _required_str(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value
