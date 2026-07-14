"""Deterministic pagination helpers for validated qspec files."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re

from answercard.schema import AnswerCardSpec, BlockSpec, QuestionSpec


_DIMENSION_RE = re.compile(r"^(?P<value>(?:0|[1-9]\d*)(?:\.\d+)?)(?P<unit>mm|pt)$")
_PAGE_HEIGHT_MM = {
    "A4": 297.0,
}
_QUESTION_TITLE_MM = 12.0
_QUESTION_NEEDSPACE_EXTRA_MM = 12.0
_QUESTION_NEEDSPACE_MIN_MM = 35.0
_QUESTION_NEEDSPACE_MAX_MM = 95.0
_PAGE_FILL_SLACK_MM = 1.5
_FRAME_TOP_FROM_PAGE_TOP_MM = 15.36
_FRAME_BOTTOM_FROM_PAGE_BOTTOM_MM = 15.36
_IN_PAGE_QUESTION_TITLE_MM = 8.0
_ANSWER_ROW_OVERHEAD_MM = 2.0
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
    page_top_spacers_mm: list[float] | None = None,
    pagination_events: list[PaginationEvent] | None = None,
) -> list[PlannedPage]:
    """Plan whole-block pages using the threshold-percentage fit rules."""

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

            block_height = _dimension_to_mm(block.height)
            if block_height + _ANSWER_ROW_OVERHEAD_MM > frame_height:
                raise ValueError(
                    f"block {block.id} height {block.height} exceeds one-page frame capacity"
                )

            show_title = block_index == 0
            title_cost = _IN_PAGE_QUESTION_TITLE_MM if show_title and current_page else 0.0
            available_height = (
                frame_height
                - current_page_cost
                - title_cost
                - _ANSWER_ROW_OVERHEAD_MM
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
                    title_cost = 0.0
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
                    title_cost = 0.0

            current_page.append(
                _PageItem(
                    question=question,
                    block=block,
                    show_title=show_title,
                    height_mm=block_height,
                )
            )
            current_page_cost += title_cost + block_height + _ANSWER_ROW_OVERHEAD_MM

    if current_page:
        pages.append(current_page)

    planned_pages: list[PlannedPage] = []
    for page_number, page_items in enumerate(pages, start=1):
        page_height_adjustment = _page_value(page_height_adjustments_mm, page_number)
        adjustment_per_block = page_height_adjustment / len(page_items) if page_items else 0.0
        planned_page = _build_planned_page(
            page_number,
            page_items,
            adjustment_per_block=adjustment_per_block,
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
