from pathlib import Path


def test_production_tree_has_no_outline_ocr_or_text_extraction_entrypoints() -> None:
    root = Path(__file__).resolve().parents[1]
    forbidden_files = [
        root / "src/answercard/extract_outline.py",
        root / "src/answercard/ocr_text.py",
        root / "src/answercard/ai_layout_skeleton.py",
        root / "scripts/extract_outline.py",
        root / "scripts/prepare_ai_layout_skeleton.py",
        root / "prompts/ai_layout_judge.md",
    ]
    assert not any(path.exists() for path in forbidden_files)
    production = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for folder in (root / "src", root / "scripts")
        for path in folder.rglob("*.py")
    ).lower()
    assert "rapidocr" not in production
    assert "extract_outline" not in production
    assert "get_textpage" not in production
