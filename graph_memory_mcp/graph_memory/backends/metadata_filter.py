"""Shared metadata_filter keys for Falkor Cypher and Arcade SQL."""

from __future__ import annotations

from typing import Any

METADATA_FILTER_KEYS = frozenset(
    {"type", "tags", "confidence_min", "project", "created_by"}
)


def validate_metadata_filter(metadata_filter: dict[str, Any] | None) -> None:
    """Raise ValueError when a key is not one the stores can filter on."""
    if not metadata_filter:
        return
    unknown = set(metadata_filter) - METADATA_FILTER_KEYS
    if unknown:
        raise ValueError(
            f"Unsupported metadata_filter keys: {sorted(unknown)}; "
            f"allowed: {sorted(METADATA_FILTER_KEYS)}"
        )
