from pathlib import Path
import json

import pytest

from answercard.ai_layout_schema import validate_ai_layout
from answercard.ai_layout_to_qspec import ai_layout_to_qspec
from answercard.schema import load_spec


def _outline() -> dict:
    return {
        "source": "reference_answer.pdf",
        "questions": [
            {
                "id": "1",
                "title": "Question One",
                "score": 10,
                "page": 1,
                "items": [{"id": "1-1", "page": 1}],
            }
        ],
    }


def _ai_layout() -> dict:
    return {
        "questions": [
            {
                "id": "1",
                "score": 10,
                "percent": 100,
                "percent_source": "printed",
                "items": [
                    {
                        "id": "1-1",
                        "kind": "short_answer",
                        "height": "24mm",
                        "fallback_after_reinspection": False,
                        "visual_requirement": "no_visual",
                        "visual_type": "none",
                    }
                ],
            }
        ]
    }


def test_ai_layout_to_qspec_uses_ai_kind_and_height(tmp_path: Path) -> None:
    outline_path = tmp_path / "outline.json"
    ai_layout_path = tmp_path / "ai_layout.json"
    qspec_path = tmp_path / "qspec.yaml"
    outline_path.write_text(json.dumps(_outline()), encoding="utf-8")
    ai_layout_path.write_text(json.dumps(_ai_layout()), encoding="utf-8")

    ai_layout_to_qspec(
        outline_path,
        ai_layout_path,
        qspec_path,
        paper_title="Chemistry Answer Card",
    )

    spec = load_spec(qspec_path)
    assert spec.schema_version == 1
    assert spec.paper.title == "Chemistry Answer Card"
    assert spec.paper.omit_front_page is False
    assert spec.paper.total_score == 10
    assert spec.questions[0].percent == 100
    assert spec.questions[0].blocks[0].id == "1-1"
    assert spec.questions[0].blocks[0].kind == "short_answer"
    assert spec.questions[0].blocks[0].height == "24mm"


def test_ai_layout_unknown_kind_requires_reinspection() -> None:
    data = _ai_layout()
    data["questions"][0]["items"][0]["kind"] = "unknown"
    data["questions"][0]["items"][0]["height"] = "95mm"

    with pytest.raises(ValueError, match="requires a second visual inspection"):
        validate_ai_layout(data)


def test_ai_layout_rejects_persisted_answer_content_key() -> None:
    data = _ai_layout()
    data["questions"][0]["items"][0]["answer_text"] = "forbidden"

    with pytest.raises(ValueError, match="forbidden"):
        validate_ai_layout(data)


def test_ai_layout_accepts_unknown_after_reinspection_with_fixed_long_height() -> None:
    data = _ai_layout()
    item = data["questions"][0]["items"][0]
    item["kind"] = "unknown"
    item["height"] = "95mm"
    item["fallback_after_reinspection"] = True

    assert validate_ai_layout(data) == data


def test_ai_layout_rejects_nonconservative_unknown_height() -> None:
    data = _ai_layout()
    item = data["questions"][0]["items"][0]
    item["kind"] = "unknown"
    item["height"] = "60mm"
    item["fallback_after_reinspection"] = True

    with pytest.raises(ValueError, match="conservative fallback 95mm"):
        validate_ai_layout(data)


@pytest.mark.parametrize("field", ["confidence", "visual_confidence"])
def test_ai_layout_rejects_removed_confidence_fields(field: str) -> None:
    data = _ai_layout()
    data["questions"][0]["items"][0][field] = 0.8

    with pytest.raises(ValueError, match="removed from the AI layout contract"):
        validate_ai_layout(data)


def test_ai_layout_requires_visible_score_and_percent_metadata() -> None:
    data = _ai_layout()
    data["questions"][0].pop("percent")

    with pytest.raises(ValueError, match="percent must be an integer"):
        validate_ai_layout(data)


def test_ai_layout_requires_explicit_percent_source() -> None:
    data = _ai_layout()
    data["questions"][0].pop("percent_source")

    with pytest.raises(ValueError, match="percent_source must be a non-empty string"):
        validate_ai_layout(data)


def test_ai_layout_rejects_height_outside_kind_range() -> None:
    data = _ai_layout()
    data["questions"][0]["items"][0]["height"] = "35mm"

    with pytest.raises(ValueError, match="between 20mm and 34mm"):
        validate_ai_layout(data)


@pytest.mark.parametrize(
    ("requirement", "visual_type"),
    [
        ("modify_existing_visual", "chemical_structure"),
        ("complete_existing_visual", "reaction_framework"),
        ("draw_on_scaffold", "coordinate_system"),
        ("draw_from_scratch", "diagram"),
        ("visual_reference_only", "table"),
        ("no_visual", "none"),
        ("uncertain", "uncertain"),
    ],
)
def test_ai_layout_accepts_visual_requirement_classes(requirement: str, visual_type: str) -> None:
    data = _ai_layout()
    item = data["questions"][0]["items"][0]
    item["visual_requirement"] = requirement
    item["visual_type"] = visual_type

    validate_ai_layout(data)


def test_ai_layout_requires_visual_requirement() -> None:
    data = _ai_layout()
    data["questions"][0]["items"][0].pop("visual_requirement")

    with pytest.raises(ValueError, match="visual_requirement must be a non-empty string"):
        validate_ai_layout(data)


def test_ai_layout_rejects_inconsistent_no_visual_type() -> None:
    data = _ai_layout()
    data["questions"][0]["items"][0]["visual_type"] = "diagram"

    with pytest.raises(ValueError, match='must be "none"'):
        validate_ai_layout(data)


def test_ai_layout_rejects_visual_context_snippet() -> None:
    data = _ai_layout()
    data["questions"][0]["items"][0]["snippet"] = "forbidden source context"

    with pytest.raises(ValueError, match="forbidden"):
        validate_ai_layout(data)


def test_ai_layout_rejects_unknown_free_text_field() -> None:
    data = _ai_layout()
    data["review_notes"] = ["free text"]

    with pytest.raises(ValueError, match="unknown field"):
        validate_ai_layout(data)


def test_ai_layout_rejects_parent_and_descendant_item_ids() -> None:
    data = _ai_layout()
    parent = dict(data["questions"][0]["items"][0])
    parent["id"] = "1-1"
    descendant = dict(parent)
    descendant["id"] = "1-1-1"
    data["questions"][0]["items"] = [parent, descendant]

    with pytest.raises(ValueError, match="parent id 1-1 and descendant id 1-1-1"):
        validate_ai_layout(data)


def test_ai_layout_to_qspec_rejects_score_mismatch(tmp_path: Path) -> None:
    outline_path = tmp_path / "outline.json"
    ai_layout_path = tmp_path / "ai_layout.json"
    qspec_path = tmp_path / "qspec.yaml"
    outline_path.write_text(json.dumps(_outline()), encoding="utf-8")
    ai_layout = _ai_layout()
    ai_layout["questions"][0]["score"] = 11
    ai_layout_path.write_text(json.dumps(ai_layout), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match outline score"):
        ai_layout_to_qspec(
            outline_path,
            ai_layout_path,
            qspec_path,
            paper_title="Chemistry Answer Card",
        )


def test_ai_layout_to_qspec_rejects_missing_outline_question(tmp_path: Path) -> None:
    outline_path = tmp_path / "outline.json"
    ai_layout_path = tmp_path / "ai_layout.json"
    qspec_path = tmp_path / "qspec.yaml"
    outline = _outline()
    outline["questions"].append(
        {
            "id": "2",
            "title": "Question Two",
            "score": 5,
            "page": 2,
            "items": [],
        }
    )
    outline_path.write_text(json.dumps(outline), encoding="utf-8")
    ai_layout = _ai_layout()
    ai_layout_path.write_text(json.dumps(ai_layout), encoding="utf-8")

    with pytest.raises(ValueError, match="question ids and order must exactly match outline"):
        ai_layout_to_qspec(
            outline_path,
            ai_layout_path,
            qspec_path,
            paper_title="Chemistry Answer Card",
        )


def test_ai_layout_to_qspec_allows_ai_block_when_outline_has_no_items(tmp_path: Path) -> None:
    outline_path = tmp_path / "outline.json"
    ai_layout_path = tmp_path / "ai_layout.json"
    qspec_path = tmp_path / "qspec.yaml"
    outline = _outline()
    outline["questions"][0]["items"] = []
    outline_path.write_text(json.dumps(outline), encoding="utf-8")
    ai_layout = _ai_layout()
    ai_layout["questions"][0]["items"][0]["id"] = "1"
    ai_layout_path.write_text(json.dumps(ai_layout), encoding="utf-8")

    ai_layout_to_qspec(
        outline_path,
        ai_layout_path,
        qspec_path,
        paper_title="Chemistry Answer Card",
    )

    spec = load_spec(qspec_path)
    assert spec.questions[0].blocks[0].id == "1"


def test_ai_layout_to_qspec_rejects_invented_subitems_when_outline_has_no_items(
    tmp_path: Path,
) -> None:
    outline_path = tmp_path / "outline.json"
    ai_layout_path = tmp_path / "ai_layout.json"
    qspec_path = tmp_path / "qspec.yaml"
    outline = _outline()
    outline["questions"][0]["items"] = []
    outline_path.write_text(json.dumps(outline), encoding="utf-8")
    ai_layout = _ai_layout()
    ai_layout["questions"][0]["items"][0]["id"] = "1-1"
    ai_layout_path.write_text(json.dumps(ai_layout), encoding="utf-8")

    with pytest.raises(ValueError, match="item ids must exactly match outline"):
        ai_layout_to_qspec(
            outline_path,
            ai_layout_path,
            qspec_path,
            paper_title="Chemistry Answer Card",
        )


def test_ai_layout_to_qspec_rejects_missing_outline_item(tmp_path: Path) -> None:
    outline_path = tmp_path / "outline.json"
    ai_layout_path = tmp_path / "ai_layout.json"
    qspec_path = tmp_path / "qspec.yaml"
    outline = _outline()
    outline["questions"][0]["items"].append({"id": "1-2", "page": 1})
    outline_path.write_text(json.dumps(outline), encoding="utf-8")
    ai_layout_path.write_text(json.dumps(_ai_layout()), encoding="utf-8")

    with pytest.raises(ValueError, match=r"missing=\['1-2'\]"):
        ai_layout_to_qspec(
            outline_path,
            ai_layout_path,
            qspec_path,
            paper_title="Chemistry Answer Card",
        )


def test_ai_layout_to_qspec_rejects_reordered_outline_items(tmp_path: Path) -> None:
    outline_path = tmp_path / "outline.json"
    ai_layout_path = tmp_path / "ai_layout.json"
    qspec_path = tmp_path / "qspec.yaml"
    outline = _outline()
    outline["questions"][0]["items"].append({"id": "1-2", "page": 1})
    outline_path.write_text(json.dumps(outline), encoding="utf-8")
    ai_layout = _ai_layout()
    second_item = dict(ai_layout["questions"][0]["items"][0])
    second_item["id"] = "1-2"
    ai_layout["questions"][0]["items"] = [second_item, ai_layout["questions"][0]["items"][0]]
    ai_layout_path.write_text(json.dumps(ai_layout), encoding="utf-8")

    with pytest.raises(ValueError, match="item order must exactly match outline"):
        ai_layout_to_qspec(
            outline_path,
            ai_layout_path,
            qspec_path,
            paper_title="Chemistry Answer Card",
        )


def test_unknown_fallback_maps_to_renderable_mixed_block(tmp_path: Path) -> None:
    outline_path = tmp_path / "outline.json"
    ai_layout_path = tmp_path / "ai_layout.json"
    qspec_path = tmp_path / "qspec.yaml"
    outline_path.write_text(json.dumps(_outline()), encoding="utf-8")
    ai_layout = _ai_layout()
    item = ai_layout["questions"][0]["items"][0]
    item["kind"] = "unknown"
    item["height"] = "95mm"
    item["fallback_after_reinspection"] = True
    ai_layout_path.write_text(json.dumps(ai_layout), encoding="utf-8")

    ai_layout_to_qspec(
        outline_path,
        ai_layout_path,
        qspec_path,
        paper_title="Chemistry Answer Card",
    )

    block = load_spec(qspec_path).questions[0].blocks[0]
    assert block.kind == "mixed"
    assert block.height == "95mm"


def test_ai_layout_to_qspec_can_explicitly_omit_front_page(tmp_path: Path) -> None:
    outline_path = tmp_path / "outline.json"
    ai_layout_path = tmp_path / "ai_layout.json"
    qspec_path = tmp_path / "qspec.yaml"
    outline_path.write_text(json.dumps(_outline()), encoding="utf-8")
    ai_layout_path.write_text(json.dumps(_ai_layout()), encoding="utf-8")

    ai_layout_to_qspec(
        outline_path,
        ai_layout_path,
        qspec_path,
        paper_title="Chemistry Answer Card",
        omit_front_page=True,
    )

    assert load_spec(qspec_path).paper.omit_front_page is True
