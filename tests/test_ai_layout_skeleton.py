from __future__ import annotations

from answercard.ai_layout_skeleton import build_ai_layout_skeleton


def test_skeleton_locks_outline_ids_and_leaves_only_decision_slots_empty() -> None:
    outline = {
        "source": "reference.pdf",
        "questions": [
            {
                "id": "1",
                "title": "Question 1",
                "score": 10,
                "page": 1,
                "items": [{"id": "1-1", "page": 1}],
            },
            {
                "id": "2",
                "title": "Question 2",
                "score": 5,
                "page": 2,
                "items": [],
            },
        ],
    }

    skeleton = build_ai_layout_skeleton(outline)

    assert [question["id"] for question in skeleton["questions"]] == ["1", "2"]
    assert skeleton["questions"][0]["score"] == 10
    assert skeleton["questions"][0]["items"][0] == {
        "id": "1-1",
        "kind": None,
        "height": None,
        "fallback_after_reinspection": False,
        "visual_requirement": None,
        "visual_type": None,
    }
    assert skeleton["questions"][1]["items"][0]["id"] == "2"
    assert "title" not in skeleton["questions"][0]
    assert "page" not in skeleton["questions"][0]


def test_skeleton_rejects_duplicate_item_ids() -> None:
    outline = {
        "questions": [
            {
                "id": "1",
                "score": 10,
                "items": [{"id": "1-1"}, {"id": "1-1"}],
            }
        ]
    }

    try:
        build_ai_layout_skeleton(outline)
    except ValueError as exc:
        assert "duplicate ids" in str(exc)
    else:
        raise AssertionError("duplicate item ids must be rejected")
