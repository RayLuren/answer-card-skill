"""Strict, answer-free contract for whole-paper visual AI output."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

CURRENT_AI_PAPER_SCHEMA_VERSION = 1
RESOLVED_KINDS = {
    "short_answer", "formula", "equation", "calculation", "drawing",
    "mechanism", "table", "multi_step", "long_explanation", "mixed",
}
ALLOWED_KINDS = RESOLVED_KINDS | {"unknown"}
FALLBACK_KIND = "unknown"
FALLBACK_HEIGHT = "95mm"
HEIGHT_RANGES_MM = {
    "formula": (16.0, 28.0), "short_answer": (20.0, 34.0),
    "equation": (24.0, 44.0), "calculation": (38.0, 80.0),
    "drawing": (34.0, 80.0), "mechanism": (55.0, 105.0),
    "table": (34.0, 80.0), "multi_step": (45.0, 95.0),
    "long_explanation": (50.0, 100.0), "mixed": (45.0, 95.0),
}
ALLOWED_VISUAL_REQUIREMENTS = {
    "modify_existing_visual", "complete_existing_visual", "draw_on_scaffold",
    "draw_from_scratch", "visual_reference_only", "no_visual", "uncertain",
}
ALLOWED_VISUAL_TYPES = {
    "chemical_structure", "diagram", "coordinate_system", "table", "grid",
    "reaction_framework", "flowchart", "apparatus", "other", "none", "uncertain",
}
PREPRINTED_VISUAL_REQUIREMENTS = {
    "modify_existing_visual", "complete_existing_visual", "draw_on_scaffold",
}
READY = "ready"
NEEDS_HUMAN_REVIEW = "needs_human_review"
STATUSES = {READY, NEEDS_HUMAN_REVIEW}
REVIEW_TARGETS = {
    "question_number",
    "question_score",
    "question_percent",
    "item_number",
}
REVIEW_REGIONS = {"top", "upper_middle", "middle", "lower_middle", "bottom"}
_HEIGHT_RE = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d+)?mm$")
_REVIEW_ID_RE = re.compile(r"r\d{3,}")
_FORBIDDEN_KEYS = {
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
    "keyword",
    "reason",
    "evidence",
    "evidence_text",
    "visual_description",
    "description",
    "notes",
    "review_notes",
    "confidence",
    "visual_confidence",
}


def load_ai_paper_spec(path: str | Path, *, page_count: int) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return validate_ai_paper_spec(data, page_count=page_count)


def validate_ai_paper_spec(data: Any, *, page_count: int) -> dict[str, Any]:
    """Validate safety and renderability without judging visible numbering."""

    if isinstance(page_count, bool) or not isinstance(page_count, int) or page_count <= 0:
        raise ValueError("page_count must be a positive integer")
    if not isinstance(data, dict):
        raise ValueError("ai_paper_spec must be a JSON object")
    _reject_forbidden_keys(data, "ai_paper_spec")
    _reject_unknown(data, {"schema_version", "status", "questions", "review_items"}, "ai_paper_spec")
    if data.get("schema_version") != CURRENT_AI_PAPER_SCHEMA_VERSION:
        raise ValueError("ai_paper_spec.schema_version must be 1")
    status = _required_str(data, "status", "ai_paper_spec")
    if status not in STATUSES:
        raise ValueError("ai_paper_spec.status is invalid")
    questions = data.get("questions")
    review_items = data.get("review_items")
    if not isinstance(questions, list):
        raise ValueError("ai_paper_spec.questions must be a list")
    if not isinstance(review_items, list):
        raise ValueError("ai_paper_spec.review_items must be a list")

    if status == READY:
        if not questions:
            raise ValueError("ready ai_paper_spec.questions must be non-empty")
        if review_items:
            raise ValueError("ready ai_paper_spec.review_items must be empty")
        for index, question in enumerate(questions):
            _validate_question(question, index=index, page_count=page_count)
    else:
        if questions:
            raise ValueError("needs_human_review must not contain a buildable partial result")
        if not review_items:
            raise ValueError("needs_human_review requires review_items")
        _validate_review_items(review_items, page_count=page_count)
    return data


def validate_human_confirmation(
    data: Any,
    *,
    paper_id: str,
    revision: int,
    review_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate a confirmation file against exactly the current review ids."""

    if not isinstance(data, dict):
        raise ValueError("human confirmation must be a JSON object")
    _reject_forbidden_keys(data, "human_confirmation")
    _reject_unknown(data, {"schema_version", "paper_id", "revision", "decisions"}, "human_confirmation")
    if data.get("schema_version") != 1:
        raise ValueError("human_confirmation.schema_version must be 1")
    if data.get("paper_id") != paper_id:
        raise ValueError("human_confirmation.paper_id does not match the paper")
    if data.get("revision") != revision:
        raise ValueError("human_confirmation.revision does not match the requested revision")
    decisions = data.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("human_confirmation.decisions must be a list")
    expected = {str(item["review_id"]) for item in review_items}
    actual: set[str] = set()
    for index, decision in enumerate(decisions):
        context = f"decisions[{index}]"
        if not isinstance(decision, dict):
            raise ValueError(f"{context} must be an object")
        _reject_unknown(decision, {"review_id", "value"}, context)
        review_id = _required_str(decision, "review_id", context)
        _required_str(decision, "value", context)
        if review_id in actual:
            raise ValueError(f"{context}.review_id duplicates {review_id}")
        actual.add(review_id)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"human confirmation review_id coverage mismatch: missing={missing}, extra={extra}")
    return data


def ai_paper_audit(data: dict[str, Any]) -> dict[str, Any]:
    """Return non-blocking, answer-free metadata for pipeline reports."""

    questions = data.get("questions", []) if data.get("status") == READY else []
    printed = [q for q in questions if q.get("percent_source") == "printed"]
    derived = [q for q in questions if q.get("percent_source") == "derived"]
    unknown_ids = [
        f"q{q_index:03d}-i{i_index:03d}"
        for q_index, question in enumerate(questions, start=1)
        for i_index, item in enumerate(question["items"], start=1)
        if item["kind"] == FALLBACK_KIND
    ]
    return {
        "ai_paper_status": data.get("status"),
        "printed_percent_total": sum(q["percent"] for q in printed),
        "derived_percent_total": sum(q["percent"] for q in derived),
        "actual_total_score": sum(q["score"] for q in questions),
        "unknown_fallback_item_ids": unknown_ids,
    }


def _validate_question(question: Any, *, index: int, page_count: int) -> None:
    context = f"questions[{index}]"
    if not isinstance(question, dict):
        raise ValueError(f"{context} must be an object")
    _reject_forbidden_keys(question, context)
    _reject_unknown(
        question,
        {"number", "title", "score", "percent", "percent_source", "source_page", "items"},
        context,
    )
    _required_str(question, "number", context)
    _required_str(question, "title", context)
    score = question.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or score <= 0:
        raise ValueError(f"{context}.score must be a positive number")
    percent = question.get("percent")
    if isinstance(percent, bool) or not isinstance(percent, int) or not 1 <= percent <= 100:
        raise ValueError(f"{context}.percent must be an integer between 1 and 100")
    if question.get("percent_source") not in {"printed", "derived"}:
        raise ValueError(f'{context}.percent_source must be "printed" or "derived"')
    _validate_page(question.get("source_page"), page_count=page_count, context=f"{context}.source_page")
    items = question.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError(f"{context}.items must be a non-empty list")
    for item_index, item in enumerate(items):
        _validate_item(item, context=f"{context}.items[{item_index}]", page_count=page_count)


def _validate_item(item: Any, *, context: str, page_count: int) -> None:
    if not isinstance(item, dict):
        raise ValueError(f"{context} must be an object")
    _reject_forbidden_keys(item, context)
    _reject_unknown(
        item,
        {"number", "source_page", "kind", "height", "fallback_after_reinspection", "visual_requirement", "visual_type"},
        context,
    )
    _required_str(item, "number", context)
    _validate_page(item.get("source_page"), page_count=page_count, context=f"{context}.source_page")
    kind = _required_str(item, "kind", context)
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"{context}.kind must be an allowed kind")
    height = _required_str(item, "height", context)
    if not _HEIGHT_RE.fullmatch(height):
        raise ValueError(f'{context}.height must be a positive millimeter dimension like "24mm"')
    height_mm = float(height[:-2])
    if height_mm <= 0:
        raise ValueError(f"{context}.height must be greater than zero")
    fallback = item.get("fallback_after_reinspection")
    if not isinstance(fallback, bool):
        raise ValueError(f"{context}.fallback_after_reinspection must be a boolean")
    if kind == FALLBACK_KIND:
        if height != FALLBACK_HEIGHT or fallback is not True:
            raise ValueError(f"{context}.unknown requires {FALLBACK_HEIGHT} and fallback_after_reinspection true")
    else:
        if fallback:
            raise ValueError(f"{context}.fallback_after_reinspection may be true only for unknown")
        minimum, maximum = HEIGHT_RANGES_MM[kind]
        if not minimum <= height_mm <= maximum:
            raise ValueError(f"{context}.height must be between {minimum:g}mm and {maximum:g}mm for kind {kind}")
    requirement = _required_str(item, "visual_requirement", context)
    if requirement not in ALLOWED_VISUAL_REQUIREMENTS:
        raise ValueError(f"{context}.visual_requirement is invalid")
    visual_type = _required_str(item, "visual_type", context)
    if visual_type not in ALLOWED_VISUAL_TYPES:
        raise ValueError(f"{context}.visual_type is invalid")
    if requirement == "no_visual" and visual_type != "none":
        raise ValueError(f'{context}.visual_type must be "none" for no_visual')
    if requirement == "uncertain" and visual_type != "uncertain":
        raise ValueError(f'{context}.visual_type must be "uncertain" for uncertain')
    if requirement not in {"no_visual", "uncertain"} and visual_type in {"none", "uncertain"}:
        raise ValueError(f"{context}.visual_type must identify the visual")


def _validate_review_items(items: list[Any], *, page_count: int) -> None:
    seen: set[str] = set()
    for index, item in enumerate(items):
        context = f"review_items[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{context} must be an object")
        _reject_forbidden_keys(item, context)
        _reject_unknown(
            item,
            {"review_id", "page", "region", "target", "question_index", "item_index", "candidates"},
            context,
        )
        review_id = _required_str(item, "review_id", context)
        if not _REVIEW_ID_RE.fullmatch(review_id):
            raise ValueError(f"{context}.review_id must match rNNN")
        if review_id in seen:
            raise ValueError(f"{context}.review_id duplicates {review_id}")
        seen.add(review_id)
        _validate_page(item.get("page"), page_count=page_count, context=f"{context}.page")
        if item.get("region") not in REVIEW_REGIONS:
            raise ValueError(f"{context}.region is invalid")
        if item.get("target") not in REVIEW_TARGETS:
            raise ValueError(f"{context}.target is invalid")
        question_index = item.get("question_index")
        if isinstance(question_index, bool) or not isinstance(question_index, int) or question_index < 0:
            raise ValueError(f"{context}.question_index must be a non-negative integer")
        item_index = item.get("item_index")
        if item_index is not None and (
            isinstance(item_index, bool) or not isinstance(item_index, int) or item_index < 0
        ):
            raise ValueError(f"{context}.item_index must be null or a non-negative integer")
        candidates = item.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError(f"{context}.candidates must be a non-empty list")
        if any(not isinstance(candidate, str) or not candidate for candidate in candidates):
            raise ValueError(f"{context}.candidates must contain non-empty strings")


def _validate_page(value: Any, *, page_count: int, context: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= page_count:
        raise ValueError(f"{context} must be between 1 and {page_count}")


def _required_str(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value


def _reject_unknown(data: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{context} contains unknown field(s): {', '.join(unknown)}")


def _reject_forbidden_keys(value: Any, context: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in _FORBIDDEN_KEYS:
                raise ValueError(f"{context}.{key} is forbidden because answer or free evidence must not persist")
            _reject_forbidden_keys(child, f"{context}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, f"{context}[{index}]")
