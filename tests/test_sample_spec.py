from answercard.schema import load_spec


def test_sample_qspec_validates_against_schema() -> None:
    spec = load_spec("spec/qspec.sample.yaml")

    assert spec.schema_version == 1
    assert spec.paper.title == "第39届 Chemy 化学奥林匹克模拟试题1答题纸"
    assert spec.paper.page_size == "A4"
    assert spec.paper.omit_front_page is True
    assert spec.paper.total_score == 29
    assert spec.paper.margin == {
        "top": "12mm",
        "bottom": "12mm",
        "left": "10mm",
        "right": "10mm",
    }
    assert [(question.id, question.title, question.score) for question in spec.questions] == [
        ("1", "元素化学", 22),
        ("2", "氟代试剂", 7),
    ]
    assert [question.percent for question in spec.questions] == [76, 24]
    assert [(block.id, block.kind, block.height) for block in spec.questions[0].blocks] == [
        ("1-1", "equation", "22mm"),
        ("1-2-1", "formula", "14mm"),
        ("1-2-2", "drawing", "42mm"),
        ("1-2-3", "equation", "42mm"),
        ("1-3", "equation", "40mm"),
        ("1-4", "equation", "55mm"),
    ]
    assert [(block.id, block.kind, block.height) for block in spec.questions[1].blocks] == [
        ("2-1", "equation", "35mm"),
        ("2-2", "drawing", "45mm"),
    ]
