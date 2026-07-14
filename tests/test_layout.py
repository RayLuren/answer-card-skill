from answercard.layout import PaginationEvent, fill_page_remainders, plan_answer_pages
from answercard.schema import AnswerCardSpec, BlockSpec, PaperSpec, QuestionSpec, StyleSpec


def test_fill_page_remainders_keeps_qspec_heights_unchanged() -> None:
    spec = AnswerCardSpec(
        paper=PaperSpec(
            title="Test",
            page_size="A4",
            omit_front_page=True,
            total_score=20,
            margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
        ),
        style=StyleSpec(label_width="13mm", border_width="0.6pt", box_gap="1.5mm", title_gap="2mm"),
        questions=[
            QuestionSpec(
                id="1",
                title="One",
                score=10,
                blocks=[
                    BlockSpec(id="1-1", kind="unknown", height="100mm"),
                    BlockSpec(id="1-2", kind="unknown", height="100mm"),
                ],
            ),
            QuestionSpec(
                id="2",
                title="Two",
                score=10,
                blocks=[BlockSpec(id="2-1", kind="unknown", height="60mm")],
            ),
        ],
    )

    filled = fill_page_remainders(spec)

    assert [block.height for block in filled.questions[0].blocks] == ["100mm", "100mm"]
    assert [block.height for block in filled.questions[1].blocks] == ["60mm"]
    assert [block.height for block in spec.questions[0].blocks] == ["100mm", "100mm"]


def test_fill_page_remainders_does_not_stretch_single_page_specs() -> None:
    spec = AnswerCardSpec(
        paper=PaperSpec(
            title="Test",
            page_size="A4",
            omit_front_page=True,
            total_score=10,
            margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
        ),
        style=StyleSpec(label_width="13mm", border_width="0.6pt", box_gap="1.5mm", title_gap="2mm"),
        questions=[
            QuestionSpec(
                id="1",
                title="One",
                score=10,
                blocks=[BlockSpec(id="1-1", kind="unknown", height="60mm")],
            ),
        ],
    )

    filled = fill_page_remainders(spec)

    assert [block.height for block in filled.questions[0].blocks] == ["60mm"]


def test_plan_answer_pages_moves_a_block_whole_to_the_next_page() -> None:
    spec = AnswerCardSpec(
        paper=PaperSpec(
            title="Test",
            page_size="A4",
            omit_front_page=True,
            total_score=20,
            margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
        ),
        style=StyleSpec(label_width="13mm", border_width="0.6pt", box_gap="1.5mm", title_gap="2mm"),
        questions=[
            QuestionSpec(
                id="1",
                title="One",
                score=10,
                blocks=[
                    BlockSpec(id="1-1", kind="calculation", height="100mm"),
                    BlockSpec(id="1-2", kind="calculation", height="100mm"),
                ],
            ),
            QuestionSpec(
                id="2",
                title="Two",
                score=10,
                blocks=[BlockSpec(id="2-1", kind="calculation", height="80mm")],
            ),
        ],
    )

    pages = plan_answer_pages(spec)

    assert len(pages) == 2
    assert [block.block.id for question in pages[0].questions for block in question.blocks] == [
        "1-1",
        "1-2",
    ]
    assert [block.block.id for question in pages[1].questions for block in question.blocks] == ["2-1"]
    assert pages[1].questions[0].blocks[0].height == "80mm"


def test_plan_answer_pages_shrinks_existing_blocks_when_whole_block_nearly_fits() -> None:
    spec = _single_question_spec(["80mm", "80mm", "99.8mm"])
    events: list[PaginationEvent] = []

    pages = plan_answer_pages(spec, pagination_events=events)

    assert len(pages) == 1
    assert [block.height for block in pages[0].questions[0].blocks] == [
        "79.5mm",
        "79.5mm",
        "99.8mm",
    ]
    assert len(events) == 1
    assert events[0].rule == "near-fit-shrink"
    assert events[0].block_id == "1-3"
    assert events[0].overflow_height_mm < 2


def test_plan_answer_pages_fills_tiny_remainder_and_moves_whole_block() -> None:
    spec = _single_question_spec(["130mm", "128mm", "50mm"])
    events: list[PaginationEvent] = []

    pages = plan_answer_pages(spec, pagination_events=events)

    assert len(pages) == 2
    assert [block.height for block in pages[0].questions[0].blocks] == [
        "131.4mm",
        "129.4mm",
    ]
    assert [block.height for block in pages[1].questions[0].blocks] == ["50mm"]
    assert len(events) == 1
    assert events[0].rule == "tiny-fragment-fill"
    assert events[0].block_id == "1-3"
    assert events[0].available_height_mm < 3


def test_plan_answer_pages_leaves_no_duplicate_ids_after_page_break() -> None:
    spec = _single_question_spec(["100mm", "100mm", "80mm"])

    pages = plan_answer_pages(spec)

    ids = [block.block.id for page in pages for question in page.questions for block in question.blocks]
    assert ids == ["1-1", "1-2", "1-3"]


def _single_question_spec(heights: list[str]) -> AnswerCardSpec:
    return AnswerCardSpec(
        paper=PaperSpec(
            title="Test",
            page_size="A4",
            omit_front_page=True,
            total_score=10,
            margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
        ),
        style=StyleSpec(label_width="13mm", border_width="0.6pt", box_gap="1.5mm", title_gap="2mm"),
        questions=[
            QuestionSpec(
                id="1",
                title="One",
                score=10,
                blocks=[
                    BlockSpec(id=f"1-{index}", kind="calculation", height=height)
                    for index, height in enumerate(heights, start=1)
                ],
            )
        ],
    )
