"""Helpers for hierarchical answer-card item IDs."""

from __future__ import annotations

from collections.abc import Iterable


def leaf_item_ids(item_ids: Iterable[str]) -> list[str]:
    """Return ids that are not strict parents of another supplied id."""

    ordered_ids = list(item_ids)
    return [
        item_id
        for item_id in ordered_ids
        if not any(
            other_id.startswith(f"{item_id}-")
            for other_id in ordered_ids
            if other_id != item_id
        )
    ]


def first_parent_descendant_pair(item_ids: Iterable[str]) -> tuple[str, str] | None:
    """Return the first parent/descendant collision, if one exists."""

    ordered_ids = list(item_ids)
    for parent_id in ordered_ids:
        for descendant_id in ordered_ids:
            if descendant_id.startswith(f"{parent_id}-"):
                return parent_id, descendant_id
    return None
