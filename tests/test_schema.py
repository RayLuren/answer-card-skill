from pathlib import Path
import re

import pytest

from answercard.schema import AnswerCardSpec, load_spec, validate_spec


def valid_spec_data() -> dict:
    return {
        "schema_version": 1,
        "paper": {
            "title": "Chemistry Answer Card",
            "page_size": "A4",
            "omit_front_page": True,
            "total_score": 20,
            "margin": {
                "top": "12mm",
                "bottom": "14mm",
                "left": "10mm",
                "right": "10mm",
            },
        },
        "style": {
            "label_width": "14pt",
            "border_width": "0.4pt",
            "box_gap": "3mm",
            "title_gap": "6mm",
        },
        "questions": [
            {
                "id": "1",
                "title": "Question 1",
                "score": 12.5,
                "percent": 63,
                "blocks": [
                    {
                        "id": "1-1",
                        "kind": "short_answer",
                        "height": "20mm",
                        "force_page_break_before": True,
                    },
                    {
                        "id": "1-2-3",
                        "kind": "calculation",
                        "height": "24mm",
                    },
                ],
            },
            {
                "id": "10",
                "title": "Question 10",
                "score": 7.5,
                "percent": 37,
                "blocks": [
                    {
                        "id": "10-3-2",
                        "kind": "long_explanation",
                        "height": "60mm",
                    }
                ],
            },
        ],
    }


def test_validate_spec_returns_typed_spec() -> None:
    spec = validate_spec(valid_spec_data())

    assert isinstance(spec, AnswerCardSpec)
    assert spec.paper.title == "Chemistry Answer Card"
    assert spec.paper.margin["top"] == "12mm"
    assert spec.style.border_width == "0.4pt"
    assert spec.questions[0].score == 12.5
    assert spec.questions[0].percent == 63
    assert spec.questions[0].blocks[0].force_page_break_before is True
    assert spec.questions[0].blocks[1].force_page_break_before is False
    assert spec.questions[1].blocks[0].id == "10-3-2"


def test_validate_spec_rejects_answer_key_phrase_in_paper_title() -> None:
    data = valid_spec_data()
    data["paper"]["title"] = "Chemistry 参考答案"

    with pytest.raises(ValueError, match="forbidden answer-key phrase"):
        validate_spec(data)


def test_load_spec_reads_yaml_file(tmp_path: Path) -> None:
    spec_path = tmp_path / "qspec.yaml"
    spec_path.write_text(
        """
schema_version: 1
paper:
  title: Chemistry Answer Card
  page_size: A4
  omit_front_page: false
  total_score: 8
  margin:
    top: 12mm
    bottom: 14mm
    left: 10mm
    right: 10mm
style:
  label_width: 14pt
  border_width: 0.4pt
  box_gap: 3mm
  title_gap: 6mm
questions:
  - id: "1"
    title: Question 1
    score: 8
    percent: 100
    blocks:
      - id: "1-1"
        kind: short_answer
        height: 20mm
""",
        encoding="utf-8",
    )

    spec = load_spec(spec_path)

    assert spec.paper.omit_front_page is False
    assert spec.questions[0].blocks[0].height == "20mm"


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("style", "label_width"), "14px", "style.label_width"),
        (("paper", "margin", "top"), "12", "paper.margin.top"),
        (("questions", 0, "blocks", 0, "height"), "1.2cm", "blocks[0].height"),
    ],
)
def test_validate_spec_rejects_invalid_dimensions(path: tuple, value: object, message: str) -> None:
    data = valid_spec_data()
    _set_path(data, path, value)

    with pytest.raises(ValueError, match=re.escape(message)):
        validate_spec(data)


@pytest.mark.parametrize("score", [0, -1, -0.1, "5", True])
def test_validate_spec_rejects_invalid_scores(score: object) -> None:
    data = valid_spec_data()
    data["questions"][0]["score"] = score

    with pytest.raises(ValueError, match=r"questions\[0\]\.score"):
        validate_spec(data)


@pytest.mark.parametrize("percent", [0, -1, -0.1, 101, 10.5, "10", True])
def test_validate_spec_rejects_invalid_percent(percent: object) -> None:
    data = valid_spec_data()
    data["questions"][0]["percent"] = percent

    with pytest.raises(ValueError, match=r"questions\[0\]\.percent"):
        validate_spec(data)


def test_validate_spec_requires_percent() -> None:
    data = valid_spec_data()
    data["questions"][0].pop("percent")

    with pytest.raises(ValueError, match=r"questions\[0\]\.percent is required"):
        validate_spec(data)


@pytest.mark.parametrize("block_id", ["1-a", "01-1", "1-", "1--2", "0-1"])
def test_validate_spec_rejects_invalid_block_ids(block_id: str) -> None:
    data = valid_spec_data()
    data["questions"][0]["blocks"][0]["id"] = block_id

    with pytest.raises(ValueError, match=r"questions\[0\]\.blocks\[0\]\.id"):
        validate_spec(data)


def test_validate_spec_requires_block_height() -> None:
    data = valid_spec_data()
    del data["questions"][0]["blocks"][0]["height"]

    with pytest.raises(ValueError, match=r"questions\[0\]\.blocks\[0\]\.height is required"):
        validate_spec(data)


def test_validate_spec_rejects_misspelled_block_height() -> None:
    data = valid_spec_data()
    block = data["questions"][0]["blocks"][0]
    del block["height"]
    block["hight"] = "20mm"

    with pytest.raises(ValueError, match=r"unsupported field\(s\): hight"):
        validate_spec(data)


@pytest.mark.parametrize("height", [22, "22"])
def test_validate_spec_rejects_dimension_without_unit(height: object) -> None:
    data = valid_spec_data()
    data["questions"][0]["blocks"][0]["height"] = height

    with pytest.raises(ValueError, match=r"questions\[0\]\.blocks\[0\]\.height"):
        validate_spec(data)


def test_validate_spec_rejects_non_numeric_block_id_text() -> None:
    data = valid_spec_data()
    data["questions"][0]["blocks"][0]["id"] = "第一题第一问"

    with pytest.raises(ValueError, match=r"questions\[0\]\.blocks\[0\]\.id"):
        validate_spec(data)


def test_validate_spec_accepts_question_id_for_single_whole_question() -> None:
    data = valid_spec_data()
    data["questions"][0]["blocks"] = [
        {
            "id": "1",
            "kind": "short_answer",
            "height": "24mm",
        }
    ]

    spec = validate_spec(data)

    assert spec.questions[0].blocks[0].id == "1"


def test_validate_spec_rejects_question_id_when_question_has_multiple_blocks() -> None:
    data = valid_spec_data()
    data["questions"][0]["blocks"][0]["id"] = "1"

    with pytest.raises(ValueError, match="only when the question has one block"):
        validate_spec(data)


def test_validate_spec_rejects_parent_and_descendant_block_ids() -> None:
    data = valid_spec_data()
    data["questions"][0]["blocks"] = [
        {"id": "1-2", "kind": "short_answer", "height": "20mm"},
        {"id": "1-2-1", "kind": "short_answer", "height": "20mm"},
    ]

    with pytest.raises(ValueError, match="parent id 1-2 and descendant id 1-2-1"):
        validate_spec(data)


def test_validate_spec_requires_known_top_level_sections() -> None:
    data = valid_spec_data()
    del data["paper"]

    with pytest.raises(ValueError, match="spec.paper is required"):
        validate_spec(data)


def test_validate_spec_rejects_unsupported_legacy_and_free_text_fields() -> None:
    data = valid_spec_data()
    data["questions"][0]["raw_heading"] = "legacy"
    data["questions"][0]["blocks"][0]["note"] = "free text"

    with pytest.raises(ValueError, match="raw_heading"):
        validate_spec(data)


def test_validate_spec_rejects_wrong_schema_version() -> None:
    data = valid_spec_data()
    data["schema_version"] = 2

    with pytest.raises(ValueError, match="schema_version must be 1"):
        validate_spec(data)


def test_validate_spec_requires_total_score_to_match_question_scores() -> None:
    data = valid_spec_data()
    data["paper"]["total_score"] = 100

    with pytest.raises(ValueError, match="must equal the sum of question scores"):
        validate_spec(data)


def test_validate_spec_preserves_nonstandard_printed_percent_total() -> None:
    data = valid_spec_data()
    data["questions"][0]["percent"] = 53

    validate_spec(data)


def test_validate_spec_rejects_duplicate_question_ids() -> None:
    data = valid_spec_data()
    data["questions"][1]["id"] = "1"
    data["questions"][1]["blocks"][0]["id"] = "1-3-2"

    with pytest.raises(ValueError, match=r"questions\[1\]\.id duplicates 1"):
        validate_spec(data)


def test_validate_spec_requires_block_id_to_match_question() -> None:
    data = valid_spec_data()
    data["questions"][0]["blocks"][0]["id"] = "2-1"

    with pytest.raises(ValueError, match="must equal question id 1 or start with 1-"):
        validate_spec(data)


def test_validate_spec_rejects_unknown_block_kind() -> None:
    data = valid_spec_data()
    data["questions"][0]["blocks"][0]["kind"] = "unknown"

    with pytest.raises(ValueError, match="allowed AI layout kinds"):
        validate_spec(data)


def _set_path(data: dict, path: tuple, value: object) -> None:
    target = data
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
