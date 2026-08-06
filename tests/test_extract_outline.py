import json
from types import SimpleNamespace

from answercard.extract_outline import (
    TextPage,
    _normalize_ocr_outline,
    extract_pdf_text,
    parse_outline,
)


def test_parse_outline_extracts_questions_items_scores_and_pages() -> None:
    pages = [
        TextPage(
            page=1,
            text="""
第 1 题 有机推断 共 12 分
1-1 写出反应方程式。（2 分）
1-2-1 画出关键中间体结构。（3 分）
""",
        ),
        TextPage(
            page=2,
            text="""
1-3 简要说明选择理由。（4 分）
第十题 综合计算 共 8 分
10-3-2 计算并推演结果。（5 分）
""",
        ),
    ]

    outline = parse_outline(pages, source="fixtures/reference_answer.pdf")

    assert outline["source"] == "fixtures/reference_answer.pdf"
    assert outline["questions"] == [
        {
            "id": "1",
            "title": "有机推断",
            "score": 12,
            "page": 1,
            "items": [
                {"id": "1-1", "page": 1},
                {"id": "1-2-1", "page": 1},
                {"id": "1-3", "page": 2},
            ],
        },
        {
            "id": "10",
            "title": "综合计算",
            "score": 8,
            "page": 2,
            "items": [
                {"id": "10-3-2", "page": 2},
            ],
        },
    ]


def test_parse_outline_does_not_store_body_text() -> None:
    outline = parse_outline(
        [
            TextPage(
                page=1,
                text="第 2 题 无机题 共 6 分\n2-1 答案正文不应写入 JSON。（2 分）",
            )
        ]
    )

    serialized = json.dumps(outline, ensure_ascii=False)

    assert "答案正文不应写入" not in serialized
    assert outline["questions"][0]["items"][0] == {
        "id": "2-1",
        "page": 1,
    }
    assert "score" not in outline["questions"][0]["items"][0]


def test_parse_outline_supports_score_after_heading_line_and_fullwidth_digits() -> None:
    outline = parse_outline(
        [
            TextPage(
                page=3,
                text="""
第３题
共 ７.５ 分
3-1 指出实验现象。（１.５ 分）
""",
            )
        ]
    )

    question = outline["questions"][0]
    assert question["id"] == "3"
    assert question["title"] == "第3题"
    assert question["score"] == 7.5
    assert question["items"][0] == {"id": "3-1", "page": 3}


def test_parse_outline_keeps_nearby_summary_before_score() -> None:
    outline = parse_outline(
        [
            TextPage(
                page=1,
                text="""
第1题 材料化学（8分）
1-1 写出必要步骤。
""",
            )
        ]
    )

    assert outline["questions"][0]["title"] == "材料化学"


def test_parse_outline_keeps_nearby_summary_after_score() -> None:
    outline = parse_outline(
        [
            TextPage(
                page=1,
                text="""
第2题（12分）配位化学
2-1 完成表格。
""",
            )
        ]
    )

    assert outline["questions"][0]["title"] == "配位化学"


def test_parse_outline_does_not_mistake_same_line_question_body_for_summary() -> None:
    outline = parse_outline(
        [
            TextPage(
                page=1,
                text="""
第1题（8分）写出下列各反应的方程式。
1-1 第一小题。
""",
            )
        ]
    )

    serialized = json.dumps(outline, ensure_ascii=False)
    assert outline["questions"][0]["title"] == "第1题"
    assert "写出下列各反应" not in serialized


def test_parse_outline_ignores_scoring_note_headings() -> None:
    outline = parse_outline(
        [
            TextPage(
                page=1,
                text="""
第1题 元素化学（22分，占12%）
第1题评判分，具体细则如下，共22分
1-1 写出方程式。（2分）
""",
            )
        ]
    )

    assert outline["questions"] == [
        {
            "id": "1",
            "title": "元素化学",
            "score": 22,
            "page": 1,
            "items": [{"id": "1-1", "page": 1}],
        }
    ]


def test_parse_outline_does_not_treat_scientific_notation_as_subitem() -> None:
    outline = parse_outline(
        [
            TextPage(
                page=1,
                text="""
第10题 动力学（10分）
速率常数为 2.0 × 10-4，区间为 10-12.67。
10-3-2 计算活化能。
（5分）
""",
            )
        ]
    )

    assert outline["questions"][0]["items"] == [{"id": "10-3-2", "page": 1}]


def test_parse_outline_does_not_treat_inline_numeric_range_as_subitem() -> None:
    outline = parse_outline(
        [
            TextPage(
                page=1,
                text="""
第5题 定量分析（8分）
样品适用范围为 5-100 mg。
5-1 说明操作目的。
""",
            )
        ]
    )

    assert outline["questions"][0]["items"] == [{"id": "5-1", "page": 1}]


def test_parse_outline_does_not_include_item_scores_from_nearby_following_line() -> None:
    outline = parse_outline(
        [
            TextPage(
                page=1,
                text="""
第3题 结构题（16分）
3-1 画出结构示意图
（2分）
3-2 写出方程式
补充说明
（3分）
""",
            )
        ]
    )

    assert outline["questions"][0]["items"] == [
        {"id": "3-1", "page": 1},
        {"id": "3-2", "page": 1},
    ]


def test_parse_outline_merges_duplicate_lines_without_item_scores() -> None:
    outline = parse_outline(
        [
            TextPage(
                page=1,
                text="""
第1题 元素化学（22分）
1-1 写出反应方程式。
1-1（共2分）
2Na + H2O -> 2NaOH + H2（2分）
""",
            )
        ]
    )

    assert outline["questions"][0]["items"] == [{"id": "1-1", "page": 1}]


def test_parse_outline_omits_item_score_even_when_score_is_present() -> None:
    outline = parse_outline(
        [
            TextPage(
                page=1,
                text="""
第1题 元素化学（22分）
1-2 画出结构。
1-2（共8分） NaCuO2（1分）
""",
            )
        ]
    )

    assert outline["questions"][0]["items"] == [{"id": "1-2", "page": 1}]


def test_parse_outline_keeps_only_leaf_ids_when_parent_group_ids_are_present() -> None:
    outline = parse_outline(
        [
            TextPage(
                page=1,
                text="""
第6题 层级题号测试（20分）
6-3 分组标题
6-3-1 第一分问
6-3-2 子分组标题
6-3-2-1 第一叶子分问
6-3-2-2 第二叶子分问
6-4 独立分问
""",
            )
        ]
    )

    assert outline["questions"][0]["items"] == [
        {"id": "6-3-1", "page": 1},
        {"id": "6-3-2-1", "page": 1},
        {"id": "6-3-2-2", "page": 1},
        {"id": "6-4", "page": 1},
    ]


def test_extract_pdf_text_uses_transient_ocr_only_for_blank_pages(monkeypatch) -> None:
    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    monkeypatch.setattr(
        "pypdf.PdfReader",
        lambda _path: SimpleNamespace(pages=[FakePage("native structure"), FakePage("")]),
    )
    calls: list[tuple[list[int], int]] = []

    def fake_ocr(_path, page_numbers, *, dpi):
        calls.append((list(page_numbers), dpi))
        return {2: "第2题（8分）\n2-1"}

    monkeypatch.setattr("answercard.ocr_text.extract_ocr_page_texts", fake_ocr)

    pages = extract_pdf_text("sample.pdf", ocr_dpi=240)

    assert pages == [
        TextPage(page=1, text="native structure"),
        TextPage(page=2, text="第2题（8分）\n2-1", from_ocr=True),
    ]
    assert calls == [([2], 240)]


def test_extract_pdf_text_can_disable_ocr_fallback(monkeypatch) -> None:
    class FakePage:
        def extract_text(self) -> str:
            return ""

    monkeypatch.setattr("pypdf.PdfReader", lambda _path: SimpleNamespace(pages=[FakePage()]))

    pages = extract_pdf_text("sample.pdf", ocr_fallback=False)

    assert pages == [TextPage(page=1, text="")]


def test_normalize_ocr_outline_merges_duplicates_and_filters_implausible_ids() -> None:
    outline = {
        "source": "sample.pdf",
        "questions": [
            {
                "id": "2",
                "title": "第2题",
                "score": 8,
                "page": 2,
                "items": [{"id": "2-2", "page": 2}, {"id": "2-12019", "page": 2}],
            },
            {
                "id": "1",
                "title": "第1题",
                "score": 6,
                "page": 1,
                "items": [{"id": "1-2", "page": 1}, {"id": "1-1", "page": 1}],
            },
            {
                "id": "2",
                "title": "第2题",
                "score": 8,
                "page": 2,
                "items": [{"id": "2-1", "page": 2}],
            },
        ],
    }

    normalized = _normalize_ocr_outline(outline, ocr_pages={1, 2})

    assert [question["id"] for question in normalized["questions"]] == ["1", "2"]
    assert [[item["id"] for item in question["items"]] for question in normalized["questions"]] == [
        ["1-1", "1-2"],
        ["2-1", "2-2"],
    ]


def test_normalize_ocr_outline_rejects_duplicate_score_conflicts() -> None:
    outline = {
        "source": "sample.pdf",
        "questions": [
            {"id": "1", "title": "第1题", "score": 6, "page": 1, "items": []},
            {"id": "1", "title": "第1题", "score": 7, "page": 1, "items": []},
        ],
    }

    try:
        _normalize_ocr_outline(outline, ocr_pages={1})
    except ValueError as exc:
        assert str(exc) == "OCR duplicate question score conflict"
    else:
        raise AssertionError("expected OCR duplicate score conflict")
