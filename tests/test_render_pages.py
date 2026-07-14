from pathlib import Path
import importlib.util

import pytest


RENDER_PAGES_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "render_pages.py"
RENDER_PAGES_SPEC = importlib.util.spec_from_file_location(
    "answercard_render_pages_script", RENDER_PAGES_SCRIPT_PATH
)
assert RENDER_PAGES_SPEC is not None
render_pages_script = importlib.util.module_from_spec(RENDER_PAGES_SPEC)
assert RENDER_PAGES_SPEC.loader is not None
RENDER_PAGES_SPEC.loader.exec_module(render_pages_script)

page_png_path = render_pages_script.page_png_path
remove_stale_page_previews = render_pages_script._remove_stale_page_previews


def test_page_png_path_uses_three_digit_one_based_names(tmp_path: Path) -> None:
    output_dir = tmp_path / "pages"

    assert page_png_path(output_dir, 1) == output_dir / "page-001.png"
    assert page_png_path(output_dir, 2) == output_dir / "page-002.png"
    assert page_png_path(output_dir, 12) == output_dir / "page-012.png"
    assert page_png_path(output_dir, 123) == output_dir / "page-123.png"


def test_page_png_path_rejects_zero_or_negative_page_numbers(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="page_number must be 1 or greater"):
        page_png_path(tmp_path, 0)

    with pytest.raises(ValueError, match="page_number must be 1 or greater"):
        page_png_path(tmp_path, -1)


def test_remove_stale_page_previews_only_removes_page_pngs(tmp_path: Path) -> None:
    stale_preview = tmp_path / "page-014.png"
    unrelated_png = tmp_path / "diagram.png"
    unrelated_text = tmp_path / "page-014.txt"
    stale_preview.write_bytes(b"old")
    unrelated_png.write_bytes(b"keep")
    unrelated_text.write_text("keep", encoding="utf-8")

    remove_stale_page_previews(tmp_path)

    assert not stale_preview.exists()
    assert unrelated_png.exists()
    assert unrelated_text.exists()
