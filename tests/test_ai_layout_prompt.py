from pathlib import Path

from answercard.ai_layout_schema import (
    ALLOWED_KINDS,
    ALLOWED_VISUAL_REQUIREMENTS,
    ALLOWED_VISUAL_TYPES,
)


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "ai_layout_judge.md"


def test_ai_layout_prompt_exists_and_names_required_inputs() -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "outline.json" in prompt
    assert "Reference PDF or rendered page images" in prompt
    assert "Extracted page text is optional" in prompt
    assert "Return only JSON" in prompt
    assert "printed whole-number `percent`" in prompt
    assert "do not derive the printed percent from the score" in prompt
    assert '"score": 12' in prompt
    assert '"percent": 10' in prompt


def test_ai_layout_prompt_lists_schema_enums() -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    for kind in ALLOWED_KINDS:
        assert f"`{kind}`" in prompt
    for visual_requirement in ALLOWED_VISUAL_REQUIREMENTS:
        assert f"`{visual_requirement}`" in prompt
    for visual_type in ALLOWED_VISUAL_TYPES:
        assert f"`{visual_type}`" in prompt


def test_ai_layout_prompt_requires_reinspection_and_reports_conservative_fallback() -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "one explicit visual reinspection" in prompt
    assert "`kind: unknown`, `height: 95mm`" in prompt
    assert "final task report" in prompt
    assert "Never output, quote, summarize, paraphrase, store, or explain solution content" in prompt
    assert "Do not perform a separate second pass" in prompt
    assert "Do not infer or reconstruct a clean base visual" in prompt
    assert "context windows" in prompt
