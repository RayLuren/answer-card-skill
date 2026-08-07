from __future__ import annotations

from pathlib import Path

import yaml

from answercard.ai_paper_to_qspec import build_qspec_from_ai_paper
from answercard.render_tex import render_spec
from answercard.schema import load_spec, validate_spec
from answercard.visual_requirements import (
    build_visual_requirements,
    validate_visual_requirements,
    visual_requirement_report_data,
)
from test_ai_paper_schema import ready_spec


def test_machine_keys_are_stable_unique_and_display_ids_are_untouched() -> None:
    qspec = build_qspec_from_ai_paper(ready_spec(), paper_title="试卷")
    spec = validate_spec(qspec)
    assert [q.id for q in spec.questions] == ["q001", "q002"]
    assert [q.display_id for q in spec.questions] == ["9", "9"]
    assert [b.id for q in spec.questions for b in q.blocks] == [
        "q001-i001", "q001-i002", "q002-i001"
    ]
    assert [b.display_id for q in spec.questions for b in q.blocks] == ["9-2", "9-2-1", "9-2"]


def test_qspec_v2_renders_display_ids_but_binds_by_machine_key() -> None:
    spec = validate_spec(build_qspec_from_ai_paper(ready_spec(), paper_title="试卷"))
    tex = render_spec(spec, image_bindings={"q002-i001": {"asset_path": "x.png", "mode": "default"}})
    assert r"\QuestionTitle{9}" in tex
    assert r"\AnswerRow{9-2}" in tex
    assert r"\AnswerImageRow{9-2}" in tex
    assert r"\AnswerRow{q001-i001}" not in tex


def test_visual_manifest_uses_machine_and_display_ids() -> None:
    manifest = build_visual_requirements(ready_spec())
    validate_visual_requirements(
        manifest,
        expected_item_ids={"q001-i001", "q001-i002", "q002-i001"},
    )
    item = manifest["questions"][1]["items"][0]
    assert item["item_id"] == "q002-i001"
    assert item["display_id"] == "9-2"
    report = visual_requirement_report_data(manifest)
    assert report["preprinted_visual_items"][0]["id"] == "q002-i001"


def test_legacy_qspec_v1_remains_readable(tmp_path: Path) -> None:
    data = {
        "schema_version": 1,
        "paper": {
            "title": "旧版",
            "page_size": "A4",
            "omit_front_page": True,
            "total_score": 10,
            "margin": {"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
        },
        "style": {"label_width": "13mm", "border_width": "0.6pt", "box_gap": "1.5mm", "title_gap": "2mm"},
        "questions": [{"id": "1", "title": "第1题", "score": 10, "percent": 100, "blocks": [{"id": "1-1", "kind": "short_answer", "height": "24mm"}]}],
    }
    path = tmp_path / "qspec.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    spec = load_spec(path)
    assert spec.questions[0].display_id == "1"
    assert spec.questions[0].blocks[0].display_id == "1-1"


def test_legacy_visual_manifest_v1_remains_readable() -> None:
    legacy = {
        "schema_version": 1,
        "questions": [{"id": "1", "items": [{"id": "1-1", "visual_requirement": "no_visual", "visual_type": "none", "requires_preprinted_visual": False}]}],
    }
    validate_visual_requirements(legacy, expected_item_ids={"1-1"})
