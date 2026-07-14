"""Answer-free audit data for the AI-layout handoff."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def audit_ai_layout_handoff(
    outline_path: str | Path,
    ai_layout_path: str | Path,
) -> dict[str, Any]:
    """Compare structural fields without persisting source or answer content."""

    outline = _load_object(outline_path, "outline")
    ai_layout = _load_object(ai_layout_path, "ai_layout")
    conflicts = _collect_conflicts(outline, ai_layout)

    questions = ai_layout.get("questions")
    printed_percent_total = 0
    percent_values_complete = isinstance(questions, list) and bool(questions)
    fallback_items: list[dict[str, str]] = []
    reinspection_required_items: list[dict[str, str]] = []
    invalid_fallback_items: list[dict[str, str]] = []
    if isinstance(questions, list):
        for question in questions:
            if not isinstance(question, dict):
                percent_values_complete = False
                continue
            percent = question.get("percent")
            if isinstance(percent, int) and not isinstance(percent, bool):
                printed_percent_total += percent
            else:
                percent_values_complete = False
            items = question.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("kind") != "unknown":
                    continue
                item_id = item.get("id")
                height = item.get("height")
                summary = {
                    "id": str(item_id) if item_id is not None else "未记录",
                    "height": str(height) if height is not None else "未记录",
                }
                if item.get("fallback_after_reinspection") is True:
                    if height == "95mm":
                        fallback_items.append(summary)
                    else:
                        invalid_fallback_items.append(summary)
                else:
                    reinspection_required_items.append(summary)

    return {
        "ai_layout_conflicts": conflicts,
        "printed_percent_total": printed_percent_total if percent_values_complete else None,
        "printed_percent_total_is_100": (
            printed_percent_total == 100 if percent_values_complete else None
        ),
        "fallback_layout_items": fallback_items,
        "reinspection_required_items": reinspection_required_items,
        "invalid_fallback_items": invalid_fallback_items,
    }


def _collect_conflicts(
    outline: dict[str, Any],
    ai_layout: dict[str, Any],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    outline_questions = _questions_by_id(outline.get("questions"))
    ai_questions = _questions_by_id(ai_layout.get("questions"))

    outline_question_order = _ordered_ids(outline.get("questions"))
    ai_question_order = _ordered_ids(ai_layout.get("questions"))
    if set(outline_question_order) == set(ai_question_order) and outline_question_order != ai_question_order:
        conflicts.append(
            {
                "code": "question_order_mismatch",
                "outline_ids": outline_question_order,
                "ai_ids": ai_question_order,
            }
        )
    duplicate_questions = _duplicate_ids(ai_question_order)
    if duplicate_questions:
        conflicts.append({"code": "duplicate_question_ids", "ids": duplicate_questions})

    outline_ids = set(outline_questions)
    ai_ids = set(ai_questions)
    missing_questions = _sorted_ids(outline_ids - ai_ids)
    extra_questions = _sorted_ids(ai_ids - outline_ids)
    if missing_questions or extra_questions:
        conflicts.append(
            {
                "code": "question_id_mismatch",
                "missing_ids": missing_questions,
                "extra_ids": extra_questions,
            }
        )

    for question_id in _sorted_ids(outline_ids & ai_ids):
        outline_question = outline_questions[question_id]
        ai_question = ai_questions[question_id]
        outline_score = outline_question.get("score")
        ai_score = ai_question.get("score")
        if _is_number(outline_score) and _is_number(ai_score) and outline_score != ai_score:
            conflicts.append(
                {
                    "code": "score_mismatch",
                    "question_id": question_id,
                    "outline_value": outline_score,
                    "ai_value": ai_score,
                }
            )

        outline_percent = outline_question.get("percent")
        ai_percent = ai_question.get("percent")
        if (
            isinstance(outline_percent, int)
            and not isinstance(outline_percent, bool)
            and isinstance(ai_percent, int)
            and not isinstance(ai_percent, bool)
            and outline_percent != ai_percent
        ):
            conflicts.append(
                {
                    "code": "percent_mismatch",
                    "question_id": question_id,
                    "outline_value": outline_percent,
                    "ai_value": ai_percent,
                }
            )

        outline_item_ids = _item_ids(outline_question.get("items"))
        expected_item_ids = outline_item_ids or {question_id}
        ai_item_ids = _item_ids(ai_question.get("items"))
        missing_items = _sorted_ids(expected_item_ids - ai_item_ids)
        extra_items = _sorted_ids(ai_item_ids - expected_item_ids)
        if missing_items or extra_items:
            conflicts.append(
                {
                    "code": "item_id_mismatch",
                    "question_id": question_id,
                    "missing_ids": missing_items,
                    "extra_ids": extra_items,
                }
            )
        outline_item_order = _ordered_ids(outline_question.get("items")) or [question_id]
        ai_item_order = _ordered_ids(ai_question.get("items"))
        if expected_item_ids == ai_item_ids and outline_item_order != ai_item_order:
            conflicts.append(
                {
                    "code": "item_order_mismatch",
                    "question_id": question_id,
                    "outline_ids": outline_item_order,
                    "ai_ids": ai_item_order,
                }
            )
        duplicate_items = _duplicate_ids(ai_item_order)
        if duplicate_items:
            conflicts.append(
                {
                    "code": "duplicate_item_ids",
                    "question_id": question_id,
                    "ids": duplicate_items,
                }
            )

    return conflicts


def _load_object(path: str | Path, label: str) -> dict[str, Any]:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a JSON object")
    return data


def _questions_by_id(value: object) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(value, list):
        return result
    for question in value:
        if not isinstance(question, dict) or question.get("id") is None:
            continue
        result[str(question["id"])] = question
    return result


def _item_ids(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        str(item["id"])
        for item in value
        if isinstance(item, dict) and item.get("id") is not None
    }


def _ordered_ids(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item["id"])
        for item in value
        if isinstance(item, dict) and item.get("id") is not None
    ]


def _duplicate_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return _sorted_ids(duplicates)


def _sorted_ids(values: set[str]) -> list[str]:
    return sorted(values, key=lambda value: (0, int(value)) if value.isdigit() else (1, value))


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
