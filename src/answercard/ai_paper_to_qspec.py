"""Convert a validated whole-paper visual AI result to qspec v2."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from answercard.ai_paper_schema import FALLBACK_HEIGHT, READY, load_ai_paper_spec
from answercard.schema import validate_spec


DEFAULT_PAPER: dict[str, Any] = {
    "title": "答题纸",
    "page_size": "A4",
    "omit_front_page": False,
    "margin": {"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
}
DEFAULT_STYLE: dict[str, Any] = {
    "label_width": "13mm",
    "border_width": "0.6pt",
    "box_gap": "1.5mm",
    "title_gap": "2mm",
}


def ai_paper_to_qspec(
    ai_paper_path: str | Path,
    output_path: str | Path,
    *,
    page_count: int,
    paper_title: str,
    omit_front_page: bool = False,
) -> Path:
    ai_paper = load_ai_paper_spec(ai_paper_path, page_count=page_count)
    qspec = build_qspec_from_ai_paper(
        ai_paper,
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


def build_qspec_from_ai_paper(
    ai_paper: dict[str, Any],
    *,
    paper_title: str,
    omit_front_page: bool = False,
) -> dict[str, Any]:
    if ai_paper.get("status") != READY:
        raise ValueError("only status ready may be converted to qspec")
    questions: list[dict[str, Any]] = []
    for question_index, question in enumerate(ai_paper["questions"], start=1):
        question_id = f"q{question_index:03d}"
        blocks = []
        for item_index, item in enumerate(question["items"], start=1):
            kind = item["kind"]
            height = item["height"]
            if kind == "unknown":
                kind = "mixed"
                height = FALLBACK_HEIGHT
            blocks.append(
                {
                    "id": f"{question_id}-i{item_index:03d}",
                    "display_id": item["number"],
                    "kind": kind,
                    "height": height,
                }
            )
        questions.append(
            {
                "id": question_id,
                "display_id": question["number"],
                "title": question["title"],
                "score": question["score"],
                "percent": question["percent"],
                "blocks": blocks,
            }
        )
    paper = {**DEFAULT_PAPER, "margin": DEFAULT_PAPER["margin"].copy()}
    paper.update(
        title=paper_title,
        omit_front_page=omit_front_page,
        total_score=sum(question["score"] for question in ai_paper["questions"]),
    )
    return {
        "schema_version": 2,
        "paper": paper,
        "style": DEFAULT_STYLE.copy(),
        "questions": questions,
    }
