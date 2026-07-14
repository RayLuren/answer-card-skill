from __future__ import annotations

import json
from pathlib import Path

import pytest

from answercard.visual_requirements import (
    export_visual_requirements,
    load_visual_requirements,
    validate_visual_requirements,
    visual_requirement_counts,
    visual_requirement_report_data,
)


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
                        "kind": "drawing",
                        "height": "55mm",
                        "fallback_after_reinspection": False,
                        "visual_requirement": "modify_existing_visual",
                        "visual_type": "chemical_structure",
                    },
                    {
                        "id": "1-2",
                        "kind": "short_answer",
                        "height": "24mm",
                        "fallback_after_reinspection": False,
                        "visual_requirement": "uncertain",
                        "visual_type": "uncertain",
                    },
                ],
            }
        ]
    }


def test_export_visual_requirements_writes_answer_free_manifest(tmp_path: Path) -> None:
    ai_layout_path = tmp_path / "ai_layout.json"
    output_path = tmp_path / "visual_requirements.json"
    ai_layout_path.write_text(json.dumps(_ai_layout()), encoding="utf-8")

    export_visual_requirements(ai_layout_path, output_path)

    data = load_visual_requirements(output_path, expected_item_ids={"1-1", "1-2"})
    first, second = data["questions"][0]["items"]
    assert first["requires_preprinted_visual"] is True
    assert second["requires_preprinted_visual"] is None
    serialized = output_path.read_text(encoding="utf-8")
    assert "matched_text" not in serialized
    assert "snippet" not in serialized
    assert "confidence" not in serialized


def test_visual_requirements_accepts_question_id_for_single_whole_question() -> None:
    data = {
        "schema_version": 1,
        "questions": [
            {
                "id": "2",
                "items": [
                    {
                        "id": "2",
                        "visual_requirement": "no_visual",
                        "visual_type": "none",
                        "requires_preprinted_visual": False,
                    }
                ],
            }
        ],
    }

    validate_visual_requirements(data, expected_item_ids={"2"})


def test_visual_requirements_rejects_inconsistent_derived_flag(tmp_path: Path) -> None:
    ai_layout_path = tmp_path / "ai_layout.json"
    output_path = tmp_path / "visual_requirements.json"
    ai_layout_path.write_text(json.dumps(_ai_layout()), encoding="utf-8")
    export_visual_requirements(ai_layout_path, output_path)
    data = json.loads(output_path.read_text(encoding="utf-8"))
    data["questions"][0]["items"][0]["requires_preprinted_visual"] = False

    with pytest.raises(ValueError, match="inconsistent"):
        validate_visual_requirements(data)


def test_visual_requirements_rejects_incompatible_visual_type(tmp_path: Path) -> None:
    ai_layout_path = tmp_path / "ai_layout.json"
    output_path = tmp_path / "visual_requirements.json"
    ai_layout_path.write_text(json.dumps(_ai_layout()), encoding="utf-8")
    export_visual_requirements(ai_layout_path, output_path)
    data = json.loads(output_path.read_text(encoding="utf-8"))
    item = data["questions"][0]["items"][0]
    item["visual_requirement"] = "no_visual"
    item["visual_type"] = "diagram"
    item["requires_preprinted_visual"] = False

    with pytest.raises(ValueError, match='must be "none"'):
        validate_visual_requirements(data)


def test_visual_requirements_checks_exact_item_coverage(tmp_path: Path) -> None:
    ai_layout_path = tmp_path / "ai_layout.json"
    output_path = tmp_path / "visual_requirements.json"
    ai_layout_path.write_text(json.dumps(_ai_layout()), encoding="utf-8")
    export_visual_requirements(ai_layout_path, output_path)

    with pytest.raises(ValueError, match="coverage mismatch"):
        load_visual_requirements(output_path, expected_item_ids={"1-1"})


def test_visual_requirement_counts_includes_all_classes(tmp_path: Path) -> None:
    ai_layout_path = tmp_path / "ai_layout.json"
    output_path = tmp_path / "visual_requirements.json"
    ai_layout_path.write_text(json.dumps(_ai_layout()), encoding="utf-8")
    export_visual_requirements(ai_layout_path, output_path)

    counts = visual_requirement_counts(load_visual_requirements(output_path))
    assert counts["modify_existing_visual"] == 1
    assert counts["uncertain"] == 1
    assert counts["no_visual"] == 0


def test_visual_requirement_report_data_lists_preprinted_and_uncertain_items(
    tmp_path: Path,
) -> None:
    ai_layout_path = tmp_path / "ai_layout.json"
    output_path = tmp_path / "visual_requirements.json"
    ai_layout_path.write_text(json.dumps(_ai_layout()), encoding="utf-8")
    export_visual_requirements(ai_layout_path, output_path)

    report_data = visual_requirement_report_data(load_visual_requirements(output_path))

    assert report_data["visual_asset_status"] == "awaiting_manual_assets"
    assert [item["id"] for item in report_data["preprinted_visual_items"]] == ["1-1"]
    assert [item["id"] for item in report_data["uncertain_visual_items"]] == ["1-2"]
