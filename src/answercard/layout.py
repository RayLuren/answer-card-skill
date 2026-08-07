"""Deterministic pagination helpers for validated qspec files."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import math
import re
import unicodedata

from answercard.schema import AnswerCardSpec, BlockSpec, QuestionSpec


_DIMENSION_RE = re.compile(r"^(?P<value>(?:0|[1-9]\d*)(?:\.\d+)?)(?P<unit>mm|pt)$")
_PAGE_HEIGHT_MM = {
    "A4": 297.0,
}
_PAGE_WIDTH_MM = {
    "A4": 210.0,
}
_QUESTION_TITLE_MM = 12.0
_QUESTION_NEEDSPACE_EXTRA_MM = 12.0
_QUESTION_NEEDSPACE_MIN_MM = 35.0
_QUESTION_NEEDSPACE_MAX_MM = 95.0
_PAGE_FILL_SLACK_MM = 1.5
_FRAME_TOP_FROM_PAGE_TOP_MM = 15.36
_FRAME_BOTTOM_FROM_PAGE_BOTTOM_MM = 15.36
# The rendered distance from one table's closing horizontal rule to the next
# table's opening rule is 4.8mm for the one-line QuestionTitle macro.  Keep
# this synchronized with the 10.5pt/12.5pt title font and 0.5mm table gap in
# tex/main.tex.j2.
_QUESTION_TITLE_BLOCK_MM = 4.8
_QUESTION_TITLE_FONT_PT = 10.5
_QUESTION_TITLE_BASELINE_PT = 12.5
_NEAR_FIT_OVERFLOW_MM = 2.0
_TINY_AVAILABLE_HEIGHT_MM = 3.0
_THRESHOLD_RATIO = 0.30


@dataclass(frozen=True)
class PlannedBlock:
    block: BlockSpec
    height: str


@dataclass(frozen=True)
class PlannedQuestion:
    question: QuestionSpec
    show_title: bool
    blocks: list[PlannedBlock]


@dataclass(frozen=True)
class PlannedPage:
    number: int
    questions: list[PlannedQuestion]
    top_spacer_mm: float = 0.0


@dataclass(frozen=True)
class PaginationEvent:
    page_number: int
    rule: str
    question_id: str
    block_id: str
    kind: str
    qspec_height: str
    available_height_mm: float
    overflow_height_mm: float
    threshold_ratio: float
    adjusted_block_count: int
    adjustment_per_block_mm: float


@dataclass(frozen=True)
class _PageItem:
    question: QuestionSpec
    block: BlockSpec
    show_title: bool
    height_mm: float


def fill_page_remainders(spec: AnswerCardSpec) -> AnswerCardSpec:
    """Compatibility helper; page-local split fragments cannot be written back to qspec."""

    return spec


def plan_answer_pages(
    spec: AnswerCardSpec,
    *,
    page_height_adjustments_mm: list[float] | None = None,
    block_height_adjustments_mm: Mapping[str, float] | None = None,
    page_top_spacers_mm: list[float] | None = None,
    pagination_events: list[PaginationEvent] | None = None,
) -> list[PlannedPage]:
    """Plan whole-block pages from rendered costs, then apply the 30% rules.

    A block's rendered cost is its requested answer height plus the configured
    horizontal rule width.  A major-question title between tables contributes
    the measured title-macro height.  Alignment growth is applied to block
    heights before the final pagination pass so it cannot bypass these costs.
    """

    page_height = _PAGE_HEIGHT_MM.get(spec.paper.page_size.upper())
    if page_height is None:
        return [_single_unplanned_page(spec)]

    frame_height = (
        page_height
        - _FRAME_TOP_FROM_PAGE_TOP_MM
        - _FRAME_BOTTOM_FROM_PAGE_BOTTOM_MM
        - _PAGE_FILL_SLACK_MM
    )
    if frame_height <= 0:
        return [_single_unplanned_page(spec)]

    border_width_mm = _dimension_to_mm(spec.style.border_width)
    if border_width_mm <= 0:
        raise ValueError("style border_width must be a positive dimension")

    requested_adjustments = {
        str(block_id): float(delta)
        for block_id, delta in (block_height_adjustments_mm or {}).items()
    }
    title_costs_mm = {
        question.id: _question_title_cost_mm(spec, question)
        for question in spec.questions
    }
    pages = _paginate_items(
        spec,
        frame_height=frame_height,
        border_width_mm=border_width_mm,
        title_costs_mm=title_costs_mm,
        block_height_adjustments_mm=requested_adjustments,
        pagination_events=None if page_height_adjustments_mm else pagination_events,
    )

    # Backwards-compatible page adjustment input.  Convert each page delta to
    # per-block growth, then paginate again.  This is deliberately a second
    # pagination pass: alignment changes must be visible to the title/rule cost
    # model and the 30% rules before TeX is rendered.
    if page_height_adjustments_mm:
        adjusted_heights = {
            item.block.id: item.height_mm
            for page_items in pages
            for item in page_items
        }
        for page_number, page_items in enumerate(pages, start=1):
            page_adjustment = _page_value(page_height_adjustments_mm, page_number)
            if not page_items or abs(page_adjustment) <= 0.001:
                continue
            adjustment_per_block = page_adjustment / len(page_items)
            for item in page_items:
                adjusted_heights[item.block.id] += adjustment_per_block

        requested_adjustments = {
            block.id: max(1.0, adjusted_heights[block.id]) - _dimension_to_mm(block.height)
            for question in spec.questions
            for block in question.blocks
        }
        pages = _paginate_items(
            spec,
            frame_height=frame_height,
            border_width_mm=border_width_mm,
            title_costs_mm=title_costs_mm,
            block_height_adjustments_mm=requested_adjustments,
            pagination_events=pagination_events,
        )

    return _build_planned_pages(pages, page_top_spacers_mm=page_top_spacers_mm)


def adjust_planned_pages(
    pages: list[PlannedPage],
    page_height_adjustments_mm: list[float],
    *,
    page_top_spacers_mm: list[float] | None = None,
) -> list[PlannedPage]:
    """Adjust an already paginated plan without re-running threshold rules."""

    if len(page_height_adjustments_mm) != len(pages):
        raise ValueError("page height adjustments must cover every planned page")

    adjusted_pages: list[PlannedPage] = []
    for page_index, (page, total_delta) in enumerate(
        zip(pages, page_height_adjustments_mm, strict=True),
        start=1,
    ):
        block_count = sum(len(question.blocks) for question in page.questions)
        if block_count == 0:
            if abs(total_delta) > 0.001:
                raise ValueError(f"planned page {page_index} has no block to adjust")
            delta_per_block = 0.0
        else:
            delta_per_block = float(total_delta) / block_count

        adjusted_questions: list[PlannedQuestion] = []
        for question in page.questions:
            adjusted_blocks: list[PlannedBlock] = []
            for block in question.blocks:
                height_mm = _dimension_to_mm(block.height) + delta_per_block
                if height_mm <= 0:
                    raise ValueError(
                        f"alignment adjustment makes block {block.block.id} non-positive"
                    )
                adjusted_blocks.append(replace(block, height=_format_mm(height_mm)))
            adjusted_questions.append(replace(question, blocks=adjusted_blocks))

        adjusted_pages.append(
            replace(
                page,
                questions=adjusted_questions,
                top_spacer_mm=max(0.0, _page_value(page_top_spacers_mm, page_index)),
            )
        )
    return adjusted_pages


def _paginate_items(
    spec: AnswerCardSpec,
    *,
    frame_height: float,
    border_width_mm: float,
    title_costs_mm: Mapping[str, float],
    block_height_adjustments_mm: Mapping[str, float],
    pagination_events: list[PaginationEvent] | None,
) -> list[list[_PageItem]]:
    """Return page items after exact fixed-overhead accounting and 30% rules."""

    pages: list[list[_PageItem]] = []
    current_page: list[_PageItem] = []
    current_page_cost = 0.0

    def finish_page() -> None:
        nonlocal current_page, current_page_cost
        if current_page:
            pages.append(current_page)
        current_page = []
        current_page_cost = 0.0

    def resize_current_page(total_delta_mm: float) -> None:
        nonlocal current_page, current_page_cost
        if not current_page or abs(total_delta_mm) <= 0.001:
            return
        delta_per_item = total_delta_mm / len(current_page)
        current_page = [
            replace(item, height_mm=max(1.0, item.height_mm + delta_per_item))
            for item in current_page
        ]
        current_page_cost += total_delta_mm

    for question in spec.questions:
        for block_index, block in enumerate(question.blocks):
            if block.force_page_break_before and current_page:
                finish_page()

            block_height = max(
                1.0,
                _dimension_to_mm(block.height)
                + float(block_height_adjustments_mm.get(block.id, 0.0)),
            )
            if block_height + border_width_mm > frame_height:
                raise ValueError(
                    f"block {block.id} height {block.height} exceeds one-page frame capacity"
                )

            show_title = block_index == 0
            # The first page frame begins below its heading.  A later question
            # heading sits between two tables and therefore consumes frame
            # height.  Continuation pages reserve the same top slot during the
            # alignment pass.
            full_title_cost = title_costs_mm[question.id] if show_title else 0.0
            title_cost = (
                full_title_cost
                if show_title and current_page
                else max(0.0, full_title_cost - _QUESTION_TITLE_BLOCK_MM)
            )
            available_height = (
                frame_height
                - current_page_cost
                - title_cost
                - border_width_mm
            )

            if block_height > available_height and current_page:
                available_ratio = max(0.0, available_height) / block_height
                overflow_height = block_height - available_height
                overflow_ratio = overflow_height / block_height

                # Priority rule: a negligible current-page fragment is discarded.
                if (
                    available_height < _TINY_AVAILABLE_HEIGHT_MM
                    and available_ratio < _THRESHOLD_RATIO
                ):
                    total_adjustment = frame_height - current_page_cost
                    if pagination_events is not None:
                        pagination_events.append(
                            PaginationEvent(
                                page_number=len(pages) + 1,
                                rule="tiny-fragment-fill",
                                question_id=question.id,
                                block_id=block.id,
                                kind=block.kind,
                                qspec_height=block.height,
                                available_height_mm=available_height,
                                overflow_height_mm=overflow_height,
                                threshold_ratio=available_ratio,
                                adjusted_block_count=len(current_page),
                                adjustment_per_block_mm=total_adjustment / len(current_page),
                            )
                        )
                    resize_current_page(total_adjustment)
                    finish_page()
                    title_cost = max(0.0, full_title_cost - _QUESTION_TITLE_BLOCK_MM)
                elif (
                    overflow_height < _NEAR_FIT_OVERFLOW_MM
                    and overflow_ratio < _THRESHOLD_RATIO
                ):
                    if pagination_events is not None:
                        pagination_events.append(
                            PaginationEvent(
                                page_number=len(pages) + 1,
                                rule="near-fit-shrink",
                                question_id=question.id,
                                block_id=block.id,
                                kind=block.kind,
                                qspec_height=block.height,
                                available_height_mm=available_height,
                                overflow_height_mm=overflow_height,
                                threshold_ratio=overflow_ratio,
                                adjusted_block_count=len(current_page),
                                adjustment_per_block_mm=-overflow_height / len(current_page),
                            )
                        )
                    resize_current_page(-overflow_height)
                else:
                    finish_page()
                    title_cost = max(0.0, full_title_cost - _QUESTION_TITLE_BLOCK_MM)

            current_page.append(
                _PageItem(
                    question=question,
                    block=block,
                    show_title=show_title,
                    height_mm=block_height,
                )
            )
            current_page_cost += title_cost + block_height + border_width_mm

    if current_page:
        pages.append(current_page)
    return pages


def _build_planned_pages(
    pages: list[list[_PageItem]],
    *,
    page_top_spacers_mm: list[float] | None,
) -> list[PlannedPage]:
    planned_pages: list[PlannedPage] = []
    for page_number, page_items in enumerate(pages, start=1):
        planned_page = _build_planned_page(
            page_number,
            page_items,
            adjustment_per_block=0.0,
        )
        planned_pages.append(
            replace(
                planned_page,
                top_spacer_mm=max(0.0, _page_value(page_top_spacers_mm, page_number)),
            )
        )
    return planned_pages


def question_needspace(question: QuestionSpec) -> str:
    """Return the local page space needed to keep a title with its first answer row."""

    return _format_mm(_question_needspace_mm(question))


def _single_unplanned_page(spec: AnswerCardSpec) -> PlannedPage:
    page_items = [
        _PageItem(
            question=question,
            block=block,
            show_title=block_index == 0,
            height_mm=_dimension_to_mm(block.height),
        )
        for question in spec.questions
        for block_index, block in enumerate(question.blocks)
    ]
    return _build_planned_page(1, page_items, adjustment_per_block=0.0)


def _build_planned_page(
    page_number: int,
    page_items: list[_PageItem],
    *,
    adjustment_per_block: float,
) -> PlannedPage:
    planned_questions: list[PlannedQuestion] = []
    current_question: QuestionSpec | None = None
    current_blocks: list[PlannedBlock] = []
    current_show_title = False

    def flush() -> None:
        nonlocal current_question, current_blocks, current_show_title
        if current_question is not None:
            planned_questions.append(
                PlannedQuestion(
                    question=current_question,
                    show_title=current_show_title,
                    blocks=current_blocks,
                )
            )
        current_question = None
        current_blocks = []
        current_show_title = False

    for item in page_items:
        question = item.question
        block = item.block
        show_title = item.show_title
        if current_question is None or current_question.id != question.id:
            flush()
            current_question = question
            current_show_title = show_title
        current_blocks.append(
            PlannedBlock(
                block=block,
                height=_format_mm(max(1.0, item.height_mm + adjustment_per_block)),
            )
        )
    flush()
    return PlannedPage(number=page_number, questions=planned_questions)


def _page_value(values: list[float] | None, page_number: int) -> float:
    if values is None or page_number > len(values):
        return 0.0
    return float(values[page_number - 1])


def _question_title_cost_mm(spec: AnswerCardSpec, question: QuestionSpec) -> float:
    """Estimate the rendered title height with the template's font and width."""

    page_width = _PAGE_WIDTH_MM.get(spec.paper.page_size.upper())
    if page_width is None:
        return _QUESTION_TITLE_BLOCK_MM
    available_width = (
        page_width
        - _dimension_to_mm(spec.paper.margin["left"])
        - _dimension_to_mm(spec.paper.margin["right"])
    )
    if available_width <= 0:
        return _QUESTION_TITLE_BLOCK_MM

    title = question.title.strip()
    if title == f"第{question.display_id}题":
        title = ""
    percent = "" if question.percent is None else f"，占 {question.percent}%"
    rendered = f"第 {question.display_id} 题 {title}（{question.score:g} 分{percent}）"
    width_units = sum(_title_character_width_units(character) for character in rendered)
    font_mm = _QUESTION_TITLE_FONT_PT * 25.4 / 72.27
    line_count = max(1, math.ceil(width_units * font_mm / available_width))
    extra_line_mm = _QUESTION_TITLE_BASELINE_PT * 25.4 / 72.27
    return _QUESTION_TITLE_BLOCK_MM + (line_count - 1) * extra_line_mm


def _title_character_width_units(character: str) -> float:
    if character.isspace():
        return 0.5
    if unicodedata.east_asian_width(character) in {"W", "F"}:
        return 1.0
    return 0.55


def _question_needspace_mm(question: QuestionSpec) -> float:
    if not question.blocks:
        return _QUESTION_NEEDSPACE_MIN_MM

    first_height = _dimension_to_mm(question.blocks[0].height)
    return min(
        _QUESTION_NEEDSPACE_MAX_MM,
        max(_QUESTION_NEEDSPACE_MIN_MM, first_height + _QUESTION_NEEDSPACE_EXTRA_MM),
    )


def _count_page_question_titles(spec: AnswerCardSpec, page_block_keys: list[str]) -> int:
    page_key_set = set(page_block_keys)
    count = 0
    for question in spec.questions:
        if question.blocks and _block_key(question, question.blocks[0]) in page_key_set:
            count += 1
    return count


def _block_key(question: QuestionSpec, block: BlockSpec) -> str:
    return f"{question.id}:{block.id}"


def _dimension_to_mm(dimension: str) -> float:
    match = _DIMENSION_RE.fullmatch(dimension)
    if match is None:
        return 0.0

    value = float(match.group("value"))
    if match.group("unit") == "pt":
        return value * 25.4 / 72.27
    return value


def _format_mm(value: float) -> str:
    if value.is_integer():
        return f"{int(value)}mm"
    return f"{value:.1f}".rstrip("0").rstrip(".") + "mm"
