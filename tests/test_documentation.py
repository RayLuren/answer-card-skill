import re
from pathlib import Path
from urllib.parse import unquote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _published_markdown_files() -> list[Path]:
    files = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "README.en.md",
        PROJECT_ROOT / "SKILL.md",
        PROJECT_ROOT / "CONTRIBUTING.md",
    ]
    files.extend(sorted((PROJECT_ROOT / "docs").rglob("*.md")))
    files.extend(sorted((PROJECT_ROOT / "references").rglob("*.md")))
    return files


def test_published_markdown_relative_links_resolve() -> None:
    missing: list[str] = []
    for markdown_path in _published_markdown_files():
        text = markdown_path.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().split()[0].strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_text = unquote(target.split("#", 1)[0])
            if not path_text:
                continue
            resolved = (markdown_path.parent / path_text).resolve()
            if not resolved.exists():
                missing.append(
                    f"{markdown_path.relative_to(PROJECT_ROOT)} -> {target}"
                )
    assert not missing, "Missing Markdown link targets:\n" + "\n".join(missing)


def test_readmes_cross_link_and_keep_safety_defaults_in_sync() -> None:
    chinese = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    english = (PROJECT_ROOT / "README.en.md").read_text(encoding="utf-8")

    assert "[English](README.en.md)" in chinese
    assert "[简体中文](README.md)" in english
    for required in ("1.1 mm", "200 DPI", "run_tests.py"):
        assert required in chinese
        assert required in english
