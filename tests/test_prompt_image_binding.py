from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from answercard.prompt_image_binding import (
    PromptImageBindingError,
    load_prompt_image_binding_manifest,
    verify_prompt_image_binding_assets,
    write_adjusted_qspec,
    write_adjusted_visual_requirements,
)
from answercard.render_tex import render_tex
from scripts import bind_prompt_images as binding_script


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_inputs(tmp_path: Path, *, required_ids: tuple[str, ...] = ("1-1", "1-2")) -> dict[str, Path]:
    qspec = tmp_path / "qspec.yaml"
    qspec.write_text(
        """
schema_version: 1
paper:
  title: Binding Test
  page_size: A4
  omit_front_page: true
  total_score: 10
  margin: {top: 12mm, bottom: 12mm, left: 10mm, right: 10mm}
style: {label_width: 13mm, border_width: 0.6pt, box_gap: 1.5mm, title_gap: 2mm}
questions:
  - id: "1"
    title: Question
    score: 10
    percent: 100
    blocks:
      - {id: "1-1", kind: drawing, height: 30mm}
      - {id: "1-2", kind: short_answer, height: 35mm}
""".lstrip(),
        encoding="utf-8",
    )
    visual = tmp_path / "visual_requirements.json"
    items = []
    for item_id in ("1-1", "1-2"):
        required = item_id in required_ids
        items.append(
            {
                "id": item_id,
                "visual_requirement": "draw_on_scaffold" if required else "no_visual",
                "visual_type": "diagram" if required else "none",
                "requires_preprinted_visual": required,
            }
        )
    visual.write_text(
        json.dumps(
            {"schema_version": 1, "questions": [{"id": "1", "items": items}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = tmp_path / "pipeline_report.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "stages": [],
                "result": {
                    "preprinted_visual_items": [
                        {
                            "id": item_id,
                            "visual_requirement": "draw_on_scaffold",
                            "visual_type": "diagram",
                        }
                        for item_id in required_ids
                    ],
                    "uncertain_visual_items": [],
                },
            }
        ),
        encoding="utf-8",
    )
    return {"qspec": qspec, "visual": visual, "report": report}


def _write_asset(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def _manifest_item(asset: Path, item_id: str, **extra: object) -> dict[str, object]:
    digest = _sha256(asset)
    item: dict[str, object] = {
        "id": item_id,
        "clean_path": asset.name,
        "clean_sha256": digest,
        "binding_asset_path": asset.name,
        "binding_asset_sha256": digest,
        "placement": {"mode": "default"},
    }
    item.update(extra)
    return item


def _write_manifest(tmp_path: Path, items: list[dict[str, object]]) -> Path:
    path = tmp_path / "prompt_image_binding.json"
    path.write_text(
        json.dumps(
            {"schema_version": 1, "approval_scope": "whole_paper", "items": items},
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def test_binding_gate_requires_whole_paper_approval(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    first = _write_asset(tmp_path, "first-clean.png", b"first")
    manifest = _write_manifest(tmp_path, [_manifest_item(first, "1-1")])

    with pytest.raises(PromptImageBindingError, match="1-2") as exc_info:
        load_prompt_image_binding_manifest(
            manifest,
            qspec_path=paths["qspec"],
            visual_requirements_path=paths["visual"],
        )

    assert exc_info.value.code == "WHOLE_PAPER_APPROVAL_INCOMPLETE"


def test_binding_gate_rejects_changed_clean_hash(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, required_ids=("1-1",))
    asset = _write_asset(tmp_path, "figure-clean.png", b"approved")
    item = _manifest_item(asset, "1-1")
    manifest = _write_manifest(tmp_path, [item])
    asset.write_bytes(b"changed")

    with pytest.raises(PromptImageBindingError) as exc_info:
        load_prompt_image_binding_manifest(
            manifest,
            qspec_path=paths["qspec"],
            visual_requirements_path=paths["visual"],
        )

    assert exc_info.value.code == "CLEAN_HASH_CHANGED"


def test_binding_gate_rechecks_manifest_before_publication(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, required_ids=("1-1",))
    asset = _write_asset(tmp_path, "figure-clean.png", b"approved")
    manifest_path = _write_manifest(tmp_path, [_manifest_item(asset, "1-1")])
    manifest = load_prompt_image_binding_manifest(
        manifest_path,
        qspec_path=paths["qspec"],
        visual_requirements_path=paths["visual"],
    )
    manifest_path.write_text(manifest_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(PromptImageBindingError) as exc_info:
        verify_prompt_image_binding_assets(manifest)

    assert exc_info.value.code == "BINDING_MANIFEST_CHANGED"


def test_default_and_special_bindings_render_deterministically(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    first = _write_asset(tmp_path, "first-clean.png", b"first")
    second = _write_asset(tmp_path, "second-clean.png", b"second")
    special = _manifest_item(
        second,
        "1-2",
        placement={"mode": "horizontal_repeat", "repeat_count": 3, "gap_mm": 0},
        height_override="52mm",
    )
    manifest_path = _write_manifest(
        tmp_path,
        [_manifest_item(first, "1-1"), special],
    )
    manifest = load_prompt_image_binding_manifest(
        manifest_path,
        qspec_path=paths["qspec"],
        visual_requirements_path=paths["visual"],
    )
    adjusted = tmp_path / "qspec.binding.yaml"

    changes = write_adjusted_qspec(paths["qspec"], adjusted, manifest)
    render_tex(
        adjusted,
        tmp_path / "answercard.tex",
        image_bindings={
            "1-1": {
                "mode": "default",
                "asset_path": "binding-assets/1-1.png",
                "repeat_count": 1,
                "gap_mm": 0,
                "total_gap_mm": 0,
            },
            "1-2": {
                "mode": "horizontal_repeat",
                "asset_path": "binding-assets/1-2.png",
                "repeat_count": 3,
                "gap_mm": 0,
                "total_gap_mm": 0,
            },
        },
    )

    original_data = yaml.safe_load(paths["qspec"].read_text(encoding="utf-8"))
    adjusted_data = yaml.safe_load(adjusted.read_text(encoding="utf-8"))
    tex = (tmp_path / "answercard.tex").read_text(encoding="utf-8")
    assert original_data["questions"][0]["blocks"][1]["height"] == "35mm"
    assert adjusted_data["questions"][0]["blocks"][1]["height"] == "52mm"
    assert changes == [{"id": "1-2", "from": "35mm", "to": "52mm"}]
    assert r"\AnswerImageRow{1-1}{30mm}{binding-assets/1-1.png}" in tex
    assert r"\AnswerImageRepeatRow{1-2}{52mm}{3}{0mm}{0mm}{%" in tex
    assert tex.count(r"\AnswerImageRepeatGraphic{binding-assets/1-2.png}{52mm}") == 3
    assert r"width=\dimexpr\linewidth-2\AnswerImagePageCenterShift-1.2mm\relax" in tex
    assert r"height=\dimexpr#2-1.2mm\relax" in tex


def test_failed_binding_keeps_formal_pdf_and_retains_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _write_inputs(tmp_path, required_ids=("1-1",))
    asset = _write_asset(tmp_path, "figure-clean.png", b"figure")
    manifest = _write_manifest(tmp_path, [_manifest_item(asset, "1-1")])
    formal_pdf = tmp_path / "answercard.pdf"
    formal_pdf.write_bytes(b"original-pdf")

    def fail_build(*args: object, **kwargs: object) -> Path:
        raise binding_script.BuildError("simulated compile failure")

    monkeypatch.setattr(binding_script, "build_answer_card", fail_build)

    with pytest.raises(binding_script.PromptImageBindingPipelineError):
        binding_script.bind_prompt_images(
            manifest,
            qspec_path=paths["qspec"],
            visual_requirements_path=paths["visual"],
            build_dir=tmp_path / "build",
            formal_pdf_path=formal_pdf,
            pipeline_report_path=paths["report"],
            temp_root=tmp_path / ".tmp",
        )

    assert formal_pdf.read_bytes() == b"original-pdf"
    report = json.loads(paths["report"].read_text(encoding="utf-8"))
    binding = report["result"]["prompt_image_binding"]
    assert binding["status"] == "failed"
    assert binding["failure_code"] == "BINDING_BUILD_FAILED"
    assert binding["failed_visual_item_ids"] == ["1-1"]
    assert list((tmp_path / "build" / "binding-failures").glob("*/binding_failure.json"))


def test_successful_binding_replaces_pdf_only_after_validation_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _write_inputs(tmp_path, required_ids=("1-1",))
    asset = _write_asset(tmp_path, "figure-clean.png", b"figure")
    manifest = _write_manifest(tmp_path, [_manifest_item(asset, "1-1")])
    formal_pdf = tmp_path / "answercard.pdf"
    formal_pdf.write_bytes(b"original-pdf")

    def fake_build(
        spec_path: Path,
        *,
        build_dir: Path,
        image_bindings: dict[str, dict[str, object]],
        **kwargs: object,
    ) -> Path:
        destination = Path(build_dir)
        assert set(image_bindings) == {"1-1"}
        assert yaml.safe_load(Path(spec_path).read_text(encoding="utf-8"))["questions"][0]["blocks"][0]["height"] == "30mm"
        destination.joinpath("answercard.pdf").write_bytes(b"validated-bound-pdf")
        destination.joinpath("answercard.tex").write_text("tex", encoding="utf-8")
        destination.joinpath("answercard.log").write_text("ok", encoding="utf-8")
        destination.joinpath("frame_alignment.json").write_text('{"passes": []}', encoding="utf-8")
        return destination / "answercard.pdf"

    def fake_render(pdf_path: Path, pages_dir: Path) -> list[Path]:
        destination = Path(pages_dir)
        destination.mkdir()
        page = destination / "page-001.png"
        page.write_bytes(b"preview")
        return [page]

    def fake_finalize(**kwargs: object) -> dict[str, object]:
        assert Path(kwargs["pdf_path"]).read_bytes() == b"validated-bound-pdf"
        return {"status": "passed"}

    monkeypatch.setattr(binding_script, "build_answer_card", fake_build)
    monkeypatch.setattr(binding_script, "render_pdf_pages", fake_render)
    monkeypatch.setattr(binding_script, "finalize_pipeline", fake_finalize)

    result = binding_script.bind_prompt_images(
        manifest,
        qspec_path=paths["qspec"],
        visual_requirements_path=paths["visual"],
        build_dir=tmp_path / "build",
        formal_pdf_path=formal_pdf,
        pipeline_report_path=paths["report"],
        temp_root=tmp_path / ".tmp",
    )

    assert result["status"] == "embedded"
    assert formal_pdf.read_bytes() == b"validated-bound-pdf"
    assert _sha256(formal_pdf) == result["published_pdf_sha256"]
    assert not list((tmp_path / ".tmp").iterdir())
    assert (tmp_path / "build" / "qspec.binding.yaml").is_file()
    assert (tmp_path / "build" / "prompt_image_binding.json").is_file()
    report = json.loads(paths["report"].read_text(encoding="utf-8"))
    assert report["result"]["embedded_visual_item_ids"] == ["1-1"]


def test_publication_failure_rolls_back_formal_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = tmp_path / "staging"
    formal_build = tmp_path / "build"
    staging.mkdir()
    for name, content in {
        "answercard.tex": b"new-tex",
        "answercard.log": b"new-log",
        "frame_alignment.json": b"new-alignment",
        "qspec.binding.yaml": b"new-qspec",
            "prompt_image_binding.json": b"new-manifest",
            "visual_requirements.json": b'{"schema_version":1,"questions":[]}',
        "answercard.pdf": b"validated-new-pdf",
        "pipeline_report.json": b'{"schema_version":1,"status":"passed","stages":[],"result":{}}',
    }.items():
        staging.joinpath(name).write_bytes(content)
    (staging / "binding-assets").mkdir()
    (staging / "binding-assets" / "1-1.png").write_bytes(b"asset")
    (staging / "pages").mkdir()
    (staging / "pages" / "page-001.png").write_bytes(b"page")
    formal_pdf = tmp_path / "formal.pdf"
    formal_pdf.write_bytes(b"original-pdf")
    formal_report = tmp_path / "pipeline_report.json"
    formal_report.write_bytes(b"original-report")
    original_atomic_copy = binding_script._atomic_copy

    def fail_report_publish(source: Path, destination: Path) -> None:
        if destination == formal_report:
            raise OSError("simulated report publication failure")
        original_atomic_copy(source, destination)

    monkeypatch.setattr(binding_script, "_atomic_copy", fail_report_publish)

    with pytest.raises(OSError, match="report publication"):
        binding_script._publish_validated_binding(
            staging=staging,
            formal_build=formal_build,
            formal_pdf=formal_pdf,
            formal_report=formal_report,
            task_report=None,
            expected_pdf_sha256=_sha256(staging / "answercard.pdf"),
        )

    assert formal_pdf.read_bytes() == b"original-pdf"
    assert formal_report.read_bytes() == b"original-report"


def test_v2_approved_original_and_anchored_placements(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    original = _write_asset(tmp_path, "source.jpg", b"approved-original")
    binding = _write_asset(tmp_path, "source-binding.png", b"deterministic-png")
    items = []
    for item_id, mode in (("1-1", "top_right"), ("1-2", "bottom_center")):
        items.append(
            {
                "id": item_id,
                "asset_source": "approved_original",
                "clean_path": original.name,
                "clean_sha256": _sha256(original),
                "binding_asset_path": binding.name,
                "binding_asset_sha256": _sha256(binding),
                "placement": {"mode": mode, "height_ratio": 0.5, "clearance_mm": 0.6},
            }
        )
    manifest_path = tmp_path / "prompt_image_binding.json"
    manifest_path.write_text(json.dumps({"schema_version": 2, "approval_scope": "whole_paper", "items": items}), encoding="utf-8")

    manifest = load_prompt_image_binding_manifest(manifest_path, qspec_path=paths["qspec"], visual_requirements_path=paths["visual"])

    assert [item.asset_source for item in manifest.items] == ["approved_original", "approved_original"]
    assert [item.placement.height_ratio for item in manifest.items] == [0.5, 0.5]


def test_v2_zero_image_cancellations_and_visual_audit(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    manifest_path = tmp_path / "prompt_image_binding.json"
    manifest_path.write_text(
        json.dumps({"schema_version": 2, "approval_scope": "whole_paper", "items": [], "cancelled_visual_item_ids": ["1-1", "1-2"], "structural_changes": []}),
        encoding="utf-8",
    )
    manifest = load_prompt_image_binding_manifest(manifest_path, qspec_path=paths["qspec"], visual_requirements_path=paths["visual"])
    adjusted_visual = tmp_path / "visual.binding.json"
    write_adjusted_visual_requirements(paths["visual"], adjusted_visual, manifest)
    data = json.loads(adjusted_visual.read_text(encoding="utf-8"))

    assert manifest.approved_item_ids == ()
    assert manifest.cancelled_visual_item_ids == ("1-1", "1-2")
    assert all(item["requires_preprinted_visual"] is False for item in data["questions"][0]["items"])


def test_v2_merges_blocks_and_applies_independent_height_override(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path, required_ids=())
    manifest_path = tmp_path / "prompt_image_binding.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "approval_scope": "whole_paper",
                "items": [],
                "cancelled_visual_item_ids": [],
                "structural_changes": [
                    {"operation": "merge_blocks", "question_id": "1", "source_ids": ["1-1", "1-2"], "target_id": "1", "kind": "drawing", "height": "60mm"},
                    {"operation": "height_override", "id": "1", "height": "108mm"},
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = load_prompt_image_binding_manifest(manifest_path, qspec_path=paths["qspec"], visual_requirements_path=paths["visual"])
    adjusted = tmp_path / "qspec.binding.yaml"
    write_adjusted_qspec(paths["qspec"], adjusted, manifest)
    block = yaml.safe_load(adjusted.read_text(encoding="utf-8"))["questions"][0]["blocks"][0]

    assert block == {"id": "1", "kind": "drawing", "height": "108mm"}
