import pytest

from answercard.ocr_text import (
    _OcrSpan,
    _line_texts,
    extract_ocr_page_texts,
    probe_pdf_text_layers,
)


def test_line_texts_groups_spans_and_preserves_left_to_right_order() -> None:
    spans = [
        _OcrSpan(text="题", left=60, top=10, right=80, bottom=30),
        _OcrSpan(text="第1", left=10, top=11, right=50, bottom=31),
        _OcrSpan(text="1-1", left=10, top=60, right=45, bottom=80),
    ]

    assert _line_texts(spans) == ["第1 题", "1-1"]


@pytest.mark.parametrize("dpi", [149, 601])
def test_extract_ocr_page_texts_rejects_unsafe_dpi_before_loading_dependencies(dpi: int) -> None:
    with pytest.raises(ValueError, match="OCR DPI"):
        extract_ocr_page_texts("sample.pdf", [1], dpi=dpi)


def test_extract_ocr_page_texts_returns_empty_mapping_for_no_pages() -> None:
    assert extract_ocr_page_texts("sample.pdf", [], dpi=220) == {}


def test_probe_pdf_text_layers_finds_text_and_blank_pages(tmp_path) -> None:
    import fitz

    pdf_path = tmp_path / "mixed.pdf"
    with fitz.open() as document:
        text_page = document.new_page()
        text_page.insert_text((72, 72), "structure")
        document.new_page()
        document.save(pdf_path)

    probe = probe_pdf_text_layers(pdf_path)

    assert probe.page_count == 2
    assert probe.text_pages == frozenset({1})
    assert probe.blank_pages == frozenset({2})
