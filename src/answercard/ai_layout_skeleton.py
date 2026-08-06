"""Generate a no-guess AI-layout skeleton from an answer-free outline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from answercard.item_id_hierarchy import first_parent_descendant_pair


def write_ai_layout_skeleton(
    outline_path: str | Path,
    output_path: str | Path,
) -> Path:
    outline = json.loads(Path(outline_path).read_text(encoding="utf-8"))
    skeleton = build_ai_layout_skeleton(outline)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(skeleton, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def build_ai_layout_skeleton(outline: Any) -> dict[str, Any]:
    if not isinstance(outline, dict):
        raise ValueError("outline must be a JSON object")
    questions = outline.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("outline.questions must be a non-empty list")

    skeleton_questions: list[dict[str, Any]] = []
    for index, question in enumerate(questions):
        context = f"outline.questions[{index}]"
        if not isinstance(question, dict):
            raise ValueError(f"{context} must be an object")
        question_id = _required_id(question, context)
        score = question.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or score <= 0:
            raise ValueError(f"{context}.score must be a positive number")
        items = question.get("items")
        if not isinstance(items, list):
            raise ValueError(f"{context}.items must be a list")
        item_ids = [_required_id(item, f"{context}.items[{item_index}]") for item_index, item in enumerate(items)]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError(f"{context}.items contains duplicate ids")
        parent_pair = first_parent_descendant_pair(item_ids)
        if parent_pair is not None:
            parent_id, descendant_id = parent_pair
            raise ValueError(
                f"{context}.items contains parent id {parent_id} and descendant id {descendant_id}"
            )
        if not item_ids:
            item_ids = [question_id]

        skeleton_questions.append(
            {
                "id": question_id,
                "score": score,
                "percent": None,
                "percent_source": None,
                "items": [
                    {
                        "id": item_id,
                        "kind": None,
                        "height": None,
                        "fallback_after_reinspection": False,
                        "visual_requirement": None,
                        "visual_type": None,
                    }
                    for item_id in item_ids
                ],
            }
        )
    return {"questions": skeleton_questions}


def _required_id(data: object, context: str) -> str:
    if not isinstance(data, dict):
        raise ValueError(f"{context} must be an object")
    value = data.get("id")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context}.id must be a non-empty string")
    return value
