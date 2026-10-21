from __future__ import annotations

import copy

import pytest

from answercard.ai_paper_schema import (
    ai_paper_audit,
    validate_ai_paper_spec,
    validate_human_confirmation,
)


def ready_spec() -> dict:
    return {
        "schema_version": 1,
        "status": "ready",
        "questions": [
            {
                "number": "9",
                "title": "第9题",
                "score": 12,
                "percent": 51,
                "percent_source": "printed",
                "source_page": 1,
                "items": [
                    {
                        "number": "9-2",
                        "source_page": 1,
                        "kind": "short_answer",
                        "height": "24mm",
                        "fallback_after_reinspection": False,
                        "visual_requirement": "no_visual",
                        "visual_type": "none",
                    },
                    {
                        "number": "9-2-1",
                        "source_page": 2,
                        "kind": "unknown",
                        "height": "95mm",
                        "fallback_after_reinspection": True,
                        "visual_requirement": "uncertain",
                        "visual_type": "uncertain",
                    },
                ],
            },
            {
                "number": "9",
                "title": "第9题",
                "score": 8,
                "percent": 48,
                "percent_source": "printed",
                "source_page": 2,
                "items": [
                    {
                        "number": "9-2",
                        "source_page": 2,
                        "kind": "formula",
                        "height": "20mm",
                        "fallback_after_reinspection": False,
                        "visual_requirement": "draw_on_scaffold",
                        "visual_type": "grid",
                    }
                ],
            },
        ],
        "review_items": [],
    }


def review_spec() -> dict:
    return {
        "schema_version": 1,
        "status": "needs_human_review",
        "questions": [],
        "review_items": [
            {
                "review_id": "r001",
                "page": 2,
                "region": "upper_middle",
                "target": "question_number",
                "question_index": 1,
                "item_index": None,
                "candidates": ["7", "1"],
            }
        ],
    }


def test_ready_allows_duplicate_and_parent_descendant_display_numbers() -> None:
    assert validate_ai_paper_spec(ready_spec(), page_count=2)["status"] == "ready"


def test_printed_percent_total_is_audit_only() -> None:
    audit = ai_paper_audit(validate_ai_paper_spec(ready_spec(), page_count=2))
    assert audit["printed_percent_total"] == 99
    assert audit["unknown_fallback_item_ids"] == ["q001-i002"]


def test_derived_percentages_require_exact_allocation_and_ordered_ties() -> None:
    data = ready_spec()
    data["questions"] = [copy.deepcopy(data["questions"][0]) for _ in range(3)]
    for question, percent in zip(data["questions"], [34, 33, 33]):
        question.update(score=1, percent=percent, percent_source="derived")
    validate_ai_paper_spec(data, page_count=2)
    data["questions"][0]["percent"] = 33
    with pytest.raises(ValueError, match="largest-remainder"):
        validate_ai_paper_spec(data, page_count=2)
    data["questions"][2]["percent"] = 34
    with pytest.raises(ValueError, match="largest-remainder"):
        validate_ai_paper_spec(data, page_count=2)


def test_ready_rejects_mixed_percentage_sources() -> None:
    data = ready_spec()
    data["questions"][0]["percent_source"] = "derived"
    with pytest.raises(ValueError, match="mix printed and derived"):
        validate_ai_paper_spec(data, page_count=2)


@pytest.mark.parametrize("field", ["answer", "reason", "evidence", "review_notes"])
def test_forbidden_answer_or_free_evidence_fields_are_rejected(field: str) -> None:
    data = ready_spec()
    data["questions"][0]["items"][0][field] = "forbidden"
    with pytest.raises(ValueError, match="forbidden"):
        validate_ai_paper_spec(data, page_count=2)


def test_unknown_requires_exact_95mm_fallback() -> None:
    data = ready_spec()
    data["questions"][0]["items"][1]["height"] = "94mm"
    with pytest.raises(ValueError, match="95mm"):
        validate_ai_paper_spec(data, page_count=2)


def test_source_page_and_kind_ranges_are_validated() -> None:
    data = ready_spec()
    data["questions"][0]["items"][0]["source_page"] = 3
    with pytest.raises(ValueError, match="between 1 and 2"):
        validate_ai_paper_spec(data, page_count=2)
    data = ready_spec()
    data["questions"][0]["items"][0]["height"] = "40mm"
    with pytest.raises(ValueError, match="between 20mm and 34mm"):
        validate_ai_paper_spec(data, page_count=2)


def test_review_request_has_fixed_fields_and_no_partial_result() -> None:
    assert validate_ai_paper_spec(review_spec(), page_count=2)["status"] == "needs_human_review"
    data = review_spec()
    data["questions"] = ready_spec()["questions"]
    with pytest.raises(ValueError, match="partial"):
        validate_ai_paper_spec(data, page_count=2)


def test_confirmation_must_cover_exact_review_ids() -> None:
    confirmation = {
        "schema_version": 1,
        "paper_id": "paper001",
        "revision": 1,
        "decisions": [{"review_id": "r001", "value": "7"}],
    }
    validate_human_confirmation(
        confirmation,
        paper_id="paper001",
        revision=1,
        review_items=review_spec()["review_items"],
    )
    bad = copy.deepcopy(confirmation)
    bad["decisions"][0]["review_id"] = "r999"
    with pytest.raises(ValueError, match="coverage mismatch"):
        validate_human_confirmation(
            bad,
            paper_id="paper001",
            revision=1,
            review_items=review_spec()["review_items"],
        )
