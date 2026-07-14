from __future__ import annotations

import json
from pathlib import Path

from answercard.ai_layout_audit import audit_ai_layout_handoff


def test_audit_records_structural_conflicts_percent_total_and_unknown_fallback(
    tmp_path: Path,
) -> None:
    outline = {
        "questions": [
            {
                "id": "1",
                "score": 10,
                "items": [{"id": "1-1"}, {"id": "1-2"}],
            }
        ]
    }
    ai_layout = {
        "questions": [
            {
                "id": "1",
                "score": 11,
                "percent": 99,
                "percent_source": "printed",
                "items": [
                    {
                        "id": "1-1",
                        "kind": "unknown",
                        "height": "95mm",
                        "fallback_after_reinspection": True,
                        "visual_requirement": "uncertain",
                        "visual_type": "uncertain",
                    }
                ],
            }
        ]
    }
    outline_path = tmp_path / "outline.json"
    ai_layout_path = tmp_path / "ai_layout.json"
    outline_path.write_text(json.dumps(outline), encoding="utf-8")
    ai_layout_path.write_text(json.dumps(ai_layout), encoding="utf-8")

    result = audit_ai_layout_handoff(outline_path, ai_layout_path)

    assert result["printed_percent_total"] == 99
    assert result["printed_percent_total_is_100"] is False
    assert result["fallback_layout_items"] == [{"id": "1-1", "height": "95mm"}]
    assert result["reinspection_required_items"] == []
    assert result["invalid_fallback_items"] == []
    assert {conflict["code"] for conflict in result["ai_layout_conflicts"]} == {
        "score_mismatch",
        "item_id_mismatch",
    }


def test_audit_records_item_order_conflict(tmp_path: Path) -> None:
    outline = {
        "questions": [
            {"id": "1", "score": 10, "items": [{"id": "1-1"}, {"id": "1-2"}]}
        ]
    }
    ai_layout = {
        "questions": [
            {
                "id": "1",
                "score": 10,
                "percent": 100,
                "percent_source": "printed",
                "items": [{"id": "1-2"}, {"id": "1-1"}],
            }
        ]
    }
    outline_path = tmp_path / "outline.json"
    ai_layout_path = tmp_path / "ai_layout.json"
    outline_path.write_text(json.dumps(outline), encoding="utf-8")
    ai_layout_path.write_text(json.dumps(ai_layout), encoding="utf-8")

    result = audit_ai_layout_handoff(outline_path, ai_layout_path)

    assert [conflict["code"] for conflict in result["ai_layout_conflicts"]] == [
        "item_order_mismatch"
    ]


def test_audit_keeps_first_unknown_in_reinspection_queue(tmp_path: Path) -> None:
    outline = {"questions": [{"id": "1", "score": 10, "items": []}]}
    ai_layout = {
        "questions": [
            {
                "id": "1",
                "score": 10,
                "percent": 100,
                "percent_source": "printed",
                "items": [
                    {
                        "id": "1",
                        "kind": "unknown",
                        "height": "95mm",
                        "fallback_after_reinspection": False,
                    }
                ],
            }
        ]
    }
    outline_path = tmp_path / "outline.json"
    ai_layout_path = tmp_path / "ai_layout.json"
    outline_path.write_text(json.dumps(outline), encoding="utf-8")
    ai_layout_path.write_text(json.dumps(ai_layout), encoding="utf-8")

    result = audit_ai_layout_handoff(outline_path, ai_layout_path)

    assert result["fallback_layout_items"] == []
    assert result["reinspection_required_items"] == [{"id": "1", "height": "95mm"}]
    assert result["invalid_fallback_items"] == []


def test_audit_separates_invalid_second_inspection_height(tmp_path: Path) -> None:
    outline = {"questions": [{"id": "1", "score": 10, "items": []}]}
    ai_layout = {
        "questions": [
            {
                "id": "1",
                "score": 10,
                "percent": 100,
                "percent_source": "printed",
                "items": [
                    {
                        "id": "1",
                        "kind": "unknown",
                        "height": "60mm",
                        "fallback_after_reinspection": True,
                    }
                ],
            }
        ]
    }
    outline_path = tmp_path / "outline.json"
    ai_layout_path = tmp_path / "ai_layout.json"
    outline_path.write_text(json.dumps(outline), encoding="utf-8")
    ai_layout_path.write_text(json.dumps(ai_layout), encoding="utf-8")

    result = audit_ai_layout_handoff(outline_path, ai_layout_path)

    assert result["fallback_layout_items"] == []
    assert result["reinspection_required_items"] == []
    assert result["invalid_fallback_items"] == [{"id": "1", "height": "60mm"}]
