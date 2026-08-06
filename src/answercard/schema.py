"""qspec.yaml schema models and validation."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Any

import yaml

from answercard.ai_layout_schema import RESOLVED_KINDS
from answercard.item_id_hierarchy import first_parent_descendant_pair


CURRENT_SCHEMA_VERSION = 1
FORBIDDEN_PAPER_TITLE_TERMS = ("参考答案", "答案及评分标准")

_DIMENSION_RE = re.compile(r"^(?P<value>(?:0|[1-9]\d*)(?:\.\d+)?)(?P<unit>mm|pt)$")
_QUESTION_ID_RE = re.compile(r"^[1-9]\d*$")
_BLOCK_ID_RE = re.compile(r"^[1-9]\d*(?:-[1-9]\d*)*$")

_SPEC_FIELDS = {"schema_version", "paper", "style", "questions"}
_PAPER_FIELDS = {"title", "page_size", "omit_front_page", "total_score", "margin"}
_MARGIN_FIELDS = {"top", "bottom", "left", "right"}
_STYLE_FIELDS = {"label_width", "border_width", "box_gap", "title_gap"}
_QUESTION_FIELDS = {"id", "title", "score", "percent", "blocks"}
_BLOCK_FIELDS = {"id", "kind", "height", "force_page_break_before"}


@dataclass(frozen=True)
class PaperSpec:
    title: str
    page_size: str
    omit_front_page: bool
    total_score: int | float
    margin: dict[str, str]


@dataclass(frozen=True)
class StyleSpec:
    label_width: str
    border_width: str
    box_gap: str
    title_gap: str


@dataclass(frozen=True)
class BlockSpec:
    id: str
    kind: str
    height: str
    force_page_break_before: bool = False


@dataclass(frozen=True)
class QuestionSpec:
    id: str
    title: str
    score: int | float
    blocks: list[BlockSpec]
    percent: int = 0


@dataclass(frozen=True)
class AnswerCardSpec:
    paper: PaperSpec
    style: StyleSpec
    questions: list[QuestionSpec]
    schema_version: int = CURRENT_SCHEMA_VERSION


def load_spec(path: str | Path) -> AnswerCardSpec:
    """Load and validate a qspec.yaml file."""

    with Path(path).open("r", encoding="utf-8") as spec_file:
        data = yaml.safe_load(spec_file)
    return validate_spec(data)


def validate_spec(data: Any) -> AnswerCardSpec:
    """Validate qspec.yaml data and return typed spec objects."""

    if not isinstance(data, dict):
        raise ValueError("spec must be a mapping")

    _reject_unknown_fields(data, _SPEC_FIELDS, "spec")
    schema_version = _required_int(data, "schema_version", "spec")
    if schema_version != CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"spec.schema_version must be {CURRENT_SCHEMA_VERSION}, got {schema_version}"
        )

    paper = _validate_paper(_required_mapping(data, "paper", "spec"))
    style = _validate_style(_required_mapping(data, "style", "spec"))
    questions_data = _required_list(data, "questions", "spec")
    if not questions_data:
        raise ValueError("spec.questions must be a non-empty list")
    questions = [_validate_question(item, index) for index, item in enumerate(questions_data)]
    _validate_question_set(questions, paper.total_score)

    return AnswerCardSpec(
        paper=paper,
        style=style,
        questions=questions,
        schema_version=schema_version,
    )


def _validate_paper(data: dict[str, Any]) -> PaperSpec:
    _reject_unknown_fields(data, _PAPER_FIELDS, "paper")
    margin_data = _required_mapping(data, "margin", "paper")
    _reject_unknown_fields(margin_data, _MARGIN_FIELDS, "paper.margin")
    margin = {
        side: _required_positive_dimension(margin_data, side, "paper.margin")
        for side in ("top", "bottom", "left", "right")
    }

    page_size = _required_str(data, "page_size", "paper")
    if page_size != "A4":
        raise ValueError('paper.page_size must be "A4"')

    total_score = _required_number(data, "total_score", "paper")
    if total_score <= 0:
        raise ValueError("paper.total_score must be greater than zero")

    title = _required_str(data, "title", "paper")
    forbidden_title_terms = [term for term in FORBIDDEN_PAPER_TITLE_TERMS if term in title]
    if forbidden_title_terms:
        raise ValueError(
            "paper.title contains forbidden answer-key phrase(s): "
            + ", ".join(forbidden_title_terms)
        )

    return PaperSpec(
        title=title,
        page_size=page_size,
        omit_front_page=_required_bool(data, "omit_front_page", "paper"),
        total_score=total_score,
        margin=margin,
    )


def _validate_style(data: dict[str, Any]) -> StyleSpec:
    _reject_unknown_fields(data, _STYLE_FIELDS, "style")
    return StyleSpec(
        label_width=_required_positive_dimension(data, "label_width", "style"),
        border_width=_required_positive_dimension(data, "border_width", "style"),
        box_gap=_required_positive_dimension(data, "box_gap", "style"),
        title_gap=_required_positive_dimension(data, "title_gap", "style"),
    )


def _validate_question(data: Any, index: int) -> QuestionSpec:
    context = f"questions[{index}]"
    if not isinstance(data, dict):
        raise ValueError(f"{context} must be a mapping")
    _reject_unknown_fields(data, _QUESTION_FIELDS, context)

    question_id = _required_str(data, "id", context)
    if not _QUESTION_ID_RE.fullmatch(question_id):
        raise ValueError(f"{context}.id must be a positive integer string")

    score = _required_number(data, "score", context)
    if score <= 0:
        raise ValueError(f"{context}.score must be greater than zero")

    percent = _required_int(data, "percent", context)
    if percent <= 0 or percent > 100:
        raise ValueError(f"{context}.percent must be an integer between 1 and 100")

    blocks_data = _required_list(data, "blocks", context)
    if not blocks_data:
        raise ValueError(f"{context}.blocks must be a non-empty list")
    blocks = [_validate_block(item, index, block_index) for block_index, item in enumerate(blocks_data)]

    seen_block_ids: set[str] = set()
    for block_index, block in enumerate(blocks):
        block_context = f"{context}.blocks[{block_index}]"
        if block.id != question_id and not block.id.startswith(f"{question_id}-"):
            raise ValueError(
                f"{block_context}.id must equal question id {question_id} "
                f"or start with {question_id}-"
            )
        if block.id in seen_block_ids:
            raise ValueError(f"{block_context}.id duplicates {block.id}")
        seen_block_ids.add(block.id)

    if len(blocks) > 1 and any(block.id == question_id for block in blocks):
        raise ValueError(
            f"{context}.blocks may use question id {question_id} only when the question has one block"
        )

    parent_pair = first_parent_descendant_pair(block.id for block in blocks)
    if parent_pair is not None:
        parent_id, descendant_id = parent_pair
        raise ValueError(
            f"{context}.blocks contains parent id {parent_id} and descendant id {descendant_id}"
        )

    return QuestionSpec(
        id=question_id,
        title=_required_str(data, "title", context),
        score=score,
        blocks=blocks,
        percent=percent,
    )


def _validate_block(data: Any, question_index: int, block_index: int) -> BlockSpec:
    context = f"questions[{question_index}].blocks[{block_index}]"
    if not isinstance(data, dict):
        raise ValueError(f"{context} must be a mapping")
    _reject_unknown_fields(data, _BLOCK_FIELDS, context)

    block_id = _required_str(data, "id", context)
    if not _BLOCK_ID_RE.fullmatch(block_id):
        raise ValueError(f"{context}.id must be a positive integer or numeric parts separated by hyphens")

    kind = _required_str(data, "kind", context)
    if kind not in RESOLVED_KINDS:
        raise ValueError(f"{context}.kind must be one of the allowed AI layout kinds")

    force_page_break_before = data.get("force_page_break_before", False)
    if not isinstance(force_page_break_before, bool):
        raise ValueError(f"{context}.force_page_break_before must be a boolean")

    return BlockSpec(
        id=block_id,
        kind=kind,
        height=_required_positive_dimension(data, "height", context),
        force_page_break_before=force_page_break_before,
    )


def _validate_question_set(questions: list[QuestionSpec], total_score: int | float) -> None:
    seen_question_ids: set[str] = set()
    for index, question in enumerate(questions):
        if question.id in seen_question_ids:
            raise ValueError(f"questions[{index}].id duplicates {question.id}")
        seen_question_ids.add(question.id)

    score_sum = sum(question.score for question in questions)
    if not math.isclose(score_sum, total_score, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(
            f"paper.total_score must equal the sum of question scores ({score_sum:g})"
        )

    # Printed percentages are evidence, not derived data. Real source headings can
    # contain independent rounding or publication errors, so preserve each value
    # and surface the actual total in the validation/task reports.


def calculate_question_percents(scores: list[int | float]) -> list[int]:
    """Allocate whole percentages from scores with the largest-remainder method."""

    if not scores or any(score <= 0 for score in scores):
        raise ValueError("scores must contain positive numbers")
    total_score = sum(scores)
    exact = [score * 100 / total_score for score in scores]
    allocated = [math.floor(value) for value in exact]
    remaining = 100 - sum(allocated)
    order = sorted(
        range(len(scores)),
        key=lambda index: (exact[index] - allocated[index], -index),
        reverse=True,
    )
    for index in order[:remaining]:
        allocated[index] += 1
    return allocated


def _required_mapping(data: dict[str, Any], key: str, context: str) -> dict[str, Any]:
    value = _required(data, key, context)
    if not isinstance(value, dict):
        raise ValueError(f"{context}.{key} must be a mapping")
    return value


def _required_list(data: dict[str, Any], key: str, context: str) -> list[Any]:
    value = _required(data, key, context)
    if not isinstance(value, list):
        raise ValueError(f"{context}.{key} must be a list")
    return value


def _required_str(data: dict[str, Any], key: str, context: str) -> str:
    value = _required(data, key, context)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value


def _required_bool(data: dict[str, Any], key: str, context: str) -> bool:
    value = _required(data, key, context)
    if not isinstance(value, bool):
        raise ValueError(f"{context}.{key} must be a boolean")
    return value


def _required_number(data: dict[str, Any], key: str, context: str) -> int | float:
    value = _required(data, key, context)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context}.{key} must be a number")
    return value


def _required_int(data: dict[str, Any], key: str, context: str) -> int:
    value = _required(data, key, context)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context}.{key} must be an integer")
    return value


def _required_positive_dimension(data: dict[str, Any], key: str, context: str) -> str:
    value = _required_str(data, key, context)
    match = _DIMENSION_RE.fullmatch(value)
    if match is None:
        raise ValueError(f'{context}.{key} must be a dimension like "12mm" or "0.4pt"')
    if float(match.group("value")) <= 0:
        raise ValueError(f"{context}.{key} must be greater than zero")
    return value


def _reject_unknown_fields(data: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{context} contains unsupported field(s): {', '.join(unknown)}")


def _required(data: dict[str, Any], key: str, context: str) -> Any:
    if key not in data:
        raise ValueError(f"{context}.{key} is required")
    return data[key]
