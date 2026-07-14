"""Validation for AI-authored answer-card layout metadata."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


RESOLVED_KINDS = {
    "short_answer",
    "formula",
    "equation",
    "calculation",
    "drawing",
    "mechanism",
    "table",
    "multi_step",
    "long_explanation",
    "mixed",
}
ALLOWED_KINDS = RESOLVED_KINDS | {"unknown"}

FALLBACK_KIND = "unknown"
FALLBACK_HEIGHT = "95mm"
HEIGHT_RANGES_MM = {
    "formula": (16.0, 28.0),
    "short_answer": (20.0, 34.0),
    "equation": (24.0, 44.0),
    "calculation": (38.0, 80.0),
    "drawing": (34.0, 80.0),
    "mechanism": (55.0, 105.0),
    "table": (34.0, 80.0),
    "multi_step": (45.0, 95.0),
    "long_explanation": (50.0, 100.0),
    "mixed": (45.0, 95.0),
}

ALLOWED_VISUAL_REQUIREMENTS = {
    "modify_existing_visual",
    "complete_existing_visual",
    "draw_on_scaffold",
    "draw_from_scratch",
    "visual_reference_only",
    "no_visual",
    "uncertain",
}

ALLOWED_VISUAL_TYPES = {
    "chemical_structure",
    "diagram",
    "coordinate_system",
    "table",
    "grid",
    "reaction_framework",
    "flowchart",
    "apparatus",
    "other",
    "none",
    "uncertain",
}

PREPRINTED_VISUAL_REQUIREMENTS = {
    "modify_existing_visual",
    "complete_existing_visual",
    "draw_on_scaffold",
}

_DIMENSION_RE = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d+)?mm$")
_FORBIDDEN_CONTENT_KEYS = {
    "answer",
    "answer_text",
    "solution",
    "solution_text",
    "final_answer",
    "explanation",
    "equation_text",
    "structure_text",
    "context",
    "context_text",
    "snippet",
    "matched_text",
    "matched_keyword",
    "reason",
    "evidence_text",
    "visual_description",
}
_REMOVED_FIELDS = {"confidence", "visual_confidence"}


def load_ai_layout(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as layout_file:
        data = json.load(layout_file)
    return validate_ai_layout(data)


def validate_ai_layout(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("ai_layout must be a JSON object")
    _reject_forbidden_keys(data, "ai_layout")
    _reject_unknown_fields(data, {"questions"}, "ai_layout")

    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("ai_layout.questions must be a non-empty list")

    seen_items: set[str] = set()
    seen_questions: set[str] = set()
    percent_total = 0
    for question_index, question in enumerate(questions):
        context = f"questions[{question_index}]"
        if not isinstance(question, dict):
            raise ValueError(f"{context} must be an object")
        _reject_forbidden_keys(question, context)
        _reject_unknown_fields(
            question,
            {"id", "score", "percent", "percent_source", "items"},
            context,
        )
        question_id = _required_str(question, "id", context)
        if question_id in seen_questions:
            raise ValueError(f"{context}.id duplicates {question_id}")
        seen_questions.add(question_id)
        score = question.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or score <= 0:
            raise ValueError(f"{context}.score must be a positive number")
        percent = question.get("percent")
        if isinstance(percent, bool) or not isinstance(percent, int) or percent <= 0 or percent > 100:
            raise ValueError(f"{context}.percent must be an integer between 1 and 100")
        percent_total += percent
        percent_source = _required_str(question, "percent_source", context)
        if percent_source not in {"printed", "derived"}:
            raise ValueError(f'{context}.percent_source must be "printed" or "derived"')
        items = question.get("items")
        if not isinstance(items, list):
            raise ValueError(f"{context}.items must be a list")
        for item_index, item in enumerate(items):
            item_context = f"{context}.items[{item_index}]"
            if not isinstance(item, dict):
                raise ValueError(f"{item_context} must be an object")
            _reject_forbidden_keys(item, item_context)
            _reject_unknown_fields(
                item,
                {
                    "id",
                    "kind",
                    "height",
                    "fallback_after_reinspection",
                    "visual_requirement",
                    "visual_type",
                },
                item_context,
            )
            item_id = _required_str(item, "id", item_context)
            if item_id in seen_items:
                raise ValueError(f"{item_context}.id duplicates {item_id}")
            seen_items.add(item_id)
            kind = _required_str(item, "kind", item_context)
            if kind not in ALLOWED_KINDS:
                raise ValueError(f"{item_context}.kind must be an allowed kind")
            height = _required_str(item, "height", item_context)
            if not _DIMENSION_RE.fullmatch(height):
                raise ValueError(f'{item_context}.height must be a millimeter dimension like "24mm"')
            height_mm = float(height[:-2])
            if height_mm <= 0:
                raise ValueError(f"{item_context}.height must be greater than zero")
            fallback_after_reinspection = item.get("fallback_after_reinspection")
            if not isinstance(fallback_after_reinspection, bool):
                raise ValueError(f"{item_context}.fallback_after_reinspection must be a boolean")
            _validate_kind_height_and_fallback(
                kind,
                height,
                height_mm,
                fallback_after_reinspection,
                context=item_context,
            )
            visual_requirement = _required_str(item, "visual_requirement", item_context)
            if visual_requirement not in ALLOWED_VISUAL_REQUIREMENTS:
                raise ValueError(f"{item_context}.visual_requirement must be an allowed visual requirement")
            visual_type = _required_str(item, "visual_type", item_context)
            if visual_type not in ALLOWED_VISUAL_TYPES:
                raise ValueError(f"{item_context}.visual_type must be an allowed visual type")
            _validate_visual_combination(
                visual_requirement,
                visual_type,
                context=item_context,
            )

    # Do not rewrite printed evidence to force a total. The actual total is
    # recorded by final validation and highlighted when it differs from 100.

    return data


def _reject_forbidden_keys(data: dict[str, Any], context: str) -> None:
    for key, value in data.items():
        if key in _REMOVED_FIELDS:
            raise ValueError(f"{context}.{key} was removed from the AI layout contract")
        if key in _FORBIDDEN_CONTENT_KEYS:
            raise ValueError(f"{context}.{key} is forbidden because answer content must not persist")
        if isinstance(value, dict):
            _reject_forbidden_keys(value, f"{context}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    _reject_forbidden_keys(item, f"{context}.{key}[{index}]")


def _required_str(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value


def _reject_unknown_fields(data: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{context} contains unknown field(s): {', '.join(unknown)}")


def _validate_visual_combination(visual_requirement: str, visual_type: str, *, context: str) -> None:
    if visual_requirement == "no_visual" and visual_type != "none":
        raise ValueError(f'{context}.visual_type must be "none" when visual_requirement is "no_visual"')
    if visual_requirement == "uncertain" and visual_type != "uncertain":
        raise ValueError(f'{context}.visual_type must be "uncertain" when visual_requirement is "uncertain"')
    if visual_requirement not in {"no_visual", "uncertain"} and visual_type in {"none", "uncertain"}:
        raise ValueError(
            f"{context}.visual_type must identify the visual when visual_requirement is {visual_requirement}"
        )


def _validate_kind_height_and_fallback(
    kind: str,
    height: str,
    height_mm: float,
    fallback_after_reinspection: bool,
    *,
    context: str,
) -> None:
    if kind == FALLBACK_KIND:
        if not fallback_after_reinspection:
            raise ValueError(
                f"{context}.kind is unknown and requires a second visual inspection; "
                "set fallback_after_reinspection only after that reinspection"
            )
        if height != FALLBACK_HEIGHT:
            raise ValueError(
                f'{context}.height must be the conservative fallback {FALLBACK_HEIGHT} '
                "when kind remains unknown after reinspection"
            )
        return

    if fallback_after_reinspection:
        raise ValueError(
            f"{context}.fallback_after_reinspection may be true only when kind is unknown"
        )
    minimum, maximum = HEIGHT_RANGES_MM[kind]
    if height_mm < minimum or height_mm > maximum:
        raise ValueError(
            f"{context}.height must be between {minimum:g}mm and {maximum:g}mm for kind {kind}"
        )
