from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from answercard.clean_image import CleanImageError, clean_output_path, prepare_clean_image


def _save(path: Path, mode: str, pixels: list[object], size: tuple[int, int]) -> None:
    image = Image.new(mode, size)
    image.putdata(pixels)
    image.save(path)


def test_clean_output_uses_sibling_png_name(tmp_path: Path) -> None:
    source = tmp_path / "figure.scan.JPG"
    assert clean_output_path(source) == tmp_path / "figure.scan-clean.png"


@pytest.mark.parametrize("name", ["figure.gif", "figure-clean.png"])
def test_clean_output_rejects_invalid_source_name(tmp_path: Path, name: str) -> None:
    with pytest.raises(CleanImageError):
        clean_output_path(tmp_path / name)


def test_transparency_is_composited_on_white_before_thresholding(tmp_path: Path) -> None:
    source = tmp_path / "alpha.png"
    _save(source, "RGBA", [(0, 0, 0, 0), (0, 0, 0, 255)], (2, 1))

    result = prepare_clean_image(source)

    with Image.open(result.output_path) as cleaned:
        assert cleaned.mode == "RGB"
        assert [cleaned.getpixel((x, 0)) for x in range(2)] == [(255, 255, 255), (0, 0, 0)]


def test_output_is_binary_white_background_and_hash_is_stable(tmp_path: Path) -> None:
    source = tmp_path / "gray.png"
    _save(source, "L", [194, 195, 255], (3, 1))

    first = prepare_clean_image(source)
    payload = first.output_path.read_bytes()
    second = prepare_clean_image(source)

    assert first.created is True
    assert second.created is False
    assert first.sha256 == second.sha256 == hashlib.sha256(payload).hexdigest()
    with Image.open(first.output_path) as cleaned:
        assert [cleaned.getpixel((x, 0)) for x in range(3)] == [
            (0, 0, 0),
            (255, 255, 255),
            (255, 255, 255),
        ]


def test_existing_different_output_is_not_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "figure.png"
    _save(source, "L", [0], (1, 1))
    output = tmp_path / "figure-clean.png"
    original = b"do-not-overwrite"
    output.write_bytes(original)

    with pytest.raises(CleanImageError, match="refusing to overwrite"):
        prepare_clean_image(source)

    assert output.read_bytes() == original


def test_decode_failure_does_not_create_output(tmp_path: Path) -> None:
    source = tmp_path / "broken.png"
    source.write_bytes(b"not an image")

    with pytest.raises(CleanImageError, match="failed to decode"):
        prepare_clean_image(source)

    assert not (tmp_path / "broken-clean.png").exists()
