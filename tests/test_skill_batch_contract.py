from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_skill_requires_fresh_whole_paper_bounded_orchestration() -> None:
    skill = (PROJECT_ROOT / "SKILL.md").read_text(encoding="utf-8")
    reference = (PROJECT_ROOT / "references" / "codex-batch-orchestration.md").read_text(
        encoding="utf-8"
    )
    combined = f"{skill}\n{reference}".lower()
    for phrase in (
        "fresh-context",
        "whole paper",
        "bounded concurrency",
        "allowed_output_path",
        "accept-ai-paper",
        "confirm-ai-paper",
        "exactly once",
    ):
        assert phrase in combined
    assert "槽位不足时" in reference
    assert "构建始终串行" in reference
    assert "does not count as the whole-paper retry" in skill
    assert "never run pdf text extraction, ocr" in skill.lower()
    assert "references/codex-batch-orchestration.md" in skill


def test_production_entry_docs_do_not_reference_retired_markdown_brief() -> None:
    entries = [
        PROJECT_ROOT / "SKILL.md",
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT.parent / "AGENTS.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in entries)
    assert "prepare_ai_layout_task.py" not in combined
    assert "ai_layout_task.md" not in combined
    assert "numbered PDF directory" not in combined
    assert "sequential-first" not in combined


def test_python_core_does_not_depend_on_codex_thread_apis() -> None:
    core = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "src" / "answercard").glob("*.py")
    )
    for forbidden in ("spawn_agent", "wait_agent", "thread API", "Codex CLI"):
        assert forbidden not in core
