"""Convert AI-authored layout metadata into a qspec draft."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from answercard.ai_layout_schema import FALLBACK_HEIGHT, load_ai_layout
from answercard.schema import CURRENT_SCHEMA_VERSION, validate_spec


DEFAULT_PAPER: dict[str, Any] = {
    "title": "答题纸",
    "page_size": "A4",
    "omit_front_page": False,
    "margin": {
        "top": "12mm",
        "bottom": "12mm",
        "left": "10mm",
        "right": "10mm",
    },
}

DEFAULT_STYLE: dict[str, Any] = {
    "label_width": "13mm",
    "border_width": "0.6pt",
    "box_gap": "1.5mm",
    "title_gap": "2mm",
}


def ai_layout_to_qspec(
    outline_path: str | Path,
    ai_layout_path: str | Path,
    output_path: str | Path,
    *,
    paper_title: str,
    omit_front_page: bool = False,
) -> Path:
    outline = _load_outline(outline_path)
    ai_layout = load_ai_layout(ai_layout_path)
    qspec = build_qspec_from_ai_layout(
        outline,
        ai_layout,
        paper_title=paper_title,
        omit_front_page=omit_front_page,
    )
    validate_spec(qspec)

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(qspec, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    return destination


def build_qspec_from_ai_layout(
    outline: dict[str, Any],
    ai_layout: dict[str, Any],
    *,
    paper_title: str,
    omit_front_page: bool = False,
) -> dict[str, Any]:
    outline_questions = {
        str(question.get("id")): question
        for question in outline.get("questions", [])
        if isinstance(question, dict) and question.get("id") is not None
    }
    ai_questions = ai_layout["questions"]
    outline_question_order = [
        str(question.get("id"))
        for question in outline.get("questions", [])
        if isinstance(question, dict) and question.get("id") is not None
    ]
    ai_question_order = [str(question["id"]) for question in ai_questions]
    if ai_question_order != outline_question_order:
        raise ValueError(
            "ai_layout question ids and order must exactly match outline; "
            f"expected={outline_question_order}, actual={ai_question_order}"
        )
    total_score = sum(ai_question["score"] for ai_question in ai_questions)

    questions = []
    for ai_question in ai_questions:
        question_id = str(ai_question["id"])
        outline_question = outline_questions.get(question_id)
        if outline_question is None:
            raise ValueError(f"ai_layout question {question_id} is not present in outline")
        outline_item_order = [
            str(item.get("id"))
            for item in outline_question.get("items", [])
            if isinstance(item, dict) and item.get("id") is not None
        ]
        outline_item_ids = set(outline_item_order)
        ai_items = ai_question["items"]
        expected_item_ids = outline_item_ids or {question_id}
        expected_item_order = outline_item_order or [question_id]
        ai_item_order = [str(item.get("id")) for item in ai_items if isinstance(item, dict)]
        ai_item_ids = set(ai_item_order)
        missing_item_ids = _sorted_ids(expected_item_ids - ai_item_ids)
        extra_item_ids = _sorted_ids(ai_item_ids - expected_item_ids)
        if missing_item_ids or extra_item_ids:
            raise ValueError(
                f"ai_layout question {question_id} item ids must exactly match outline; "
                f"missing={missing_item_ids}, extra={extra_item_ids}"
            )
        if ai_item_order != expected_item_order:
            raise ValueError(
                f"ai_layout question {question_id} item order must exactly match outline; "
                f"expected={expected_item_order}, actual={ai_item_order}"
            )
        blocks = []
        for item in ai_items:
            item_id = str(item["id"])
            kind = item["kind"]
            height = item["height"]
            if kind == "unknown":
                kind = "mixed"
                height = FALLBACK_HEIGHT
            blocks.append(
                {
                    "id": item_id,
                    "kind": kind,
                    "height": height,
                }
            )
        if _positive_number(outline_question.get("score")) and not blocks:
            raise ValueError(f"ai_layout question {question_id} has score but no blocks")
        score = ai_question["score"]
        outline_score = outline_question.get("score")
        if _positive_number(outline_score) and score != outline_score:
            raise ValueError(
                f"ai_layout question {question_id} score {score} does not match outline score {outline_score}"
            )
        outline_percent = outline_question.get("percent")
        if outline_percent is not None and ai_question["percent"] != outline_percent:
            raise ValueError(
                f"ai_layout question {question_id} percent {ai_question['percent']} "
                f"does not match outline percent {outline_percent}"
            )
        questions.append(
            {
                "id": question_id,
                "title": outline_question.get("title") or f"第{question_id}题",
                "score": score,
                "percent": ai_question["percent"],
                "blocks": blocks,
            }
        )

    outline_question_ids = set(outline_questions)
    ai_question_ids = {str(question["id"]) for question in ai_questions}
    missing = sorted(outline_question_ids - ai_question_ids, key=lambda value: int(value) if value.isdigit() else value)
    if missing:
        raise ValueError("ai_layout is missing outline question(s): " + ", ".join(missing))

    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "paper": _build_paper(
            total_score,
            paper_title=paper_title,
            omit_front_page=omit_front_page,
        ),
        "style": DEFAULT_STYLE.copy(),
        "questions": questions,
    }


def _build_paper(
    total_score: int | float,
    *,
    paper_title: str,
    omit_front_page: bool,
) -> dict[str, Any]:
    paper = {
        **DEFAULT_PAPER,
        "margin": DEFAULT_PAPER["margin"].copy(),
    }
    paper["title"] = paper_title
    paper["omit_front_page"] = omit_front_page
    paper["total_score"] = total_score
    return paper


def _load_outline(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as outline_file:
        outline = json.load(outline_file)
    if not isinstance(outline, dict):
        raise ValueError("outline must be a JSON object")
    return outline


def _positive_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _sorted_ids(values: set[str]) -> list[str]:
    return sorted(values, key=lambda value: (0, int(value)) if value.isdigit() else (1, value))
