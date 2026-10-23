"""Server-controlled clocks and mode-specific attribution.

``created_at`` / ``updated_at`` are always set by the server.

Client and header mode copy ``created_by`` / ``updated_by`` from metadata
(or relation properties) when those keys are present, and leave the fields
empty when they are absent. ``metadata.created_by`` stays in the stored JSON.

Token mode sets both fields from the API key name. Client-supplied
``created_by``, ``updated_by``, ``created_at``, and ``updated_at`` do not
become the protected node or edge fields.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

PROTECTED_FIELDS = frozenset({"created_by", "created_at", "updated_by", "updated_at"})


def strip_protected(data: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a copy without server-owned authorship fields."""
    if not data:
        return {}
    return {key: value for key, value in data.items() if key not in PROTECTED_FIELDS}


def strip_protected_inplace(data: MutableMapping[str, Any] | None) -> None:
    if not data:
        return
    for key in PROTECTED_FIELDS:
        data.pop(key, None)


def in_token_request() -> bool:
    """True when this call is an HTTP request authenticated by an API key."""
    from graph_memory_mcp.graph_memory.owner_scope import bound_key

    return bound_key() is not None


def _field(source: Mapping[str, Any] | None, key: str) -> str | None:
    if not source or key not in source or source.get(key) is None:
        return None
    text = str(source.get(key)).strip()
    return text or None


def authors_for_write(
    source: Mapping[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """``(created_by, updated_by)`` for a node or edge write.

    Token mode uses the key name for both and ignores ``source``.
    Client and header mode read ``created_by`` and ``updated_by`` from
    ``source`` (node metadata or relation properties). A missing key stays empty.
    """
    if in_token_request():
        from graph_memory_mcp.graph_memory.owner_scope import bound_key_name

        name = bound_key_name()
        return name, name
    return _field(source, "created_by"), _field(source, "updated_by")


def metadata_for_store(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Metadata JSON stored on a node.

    ``created_at`` and ``updated_at`` are server clocks and are never stored
    from the client. ``created_by`` and ``updated_by`` stay in the JSON in
    client and header mode. Token mode drops them: the key name is the only
    attribution stored on the node properties.
    """
    stored = dict(metadata or {})
    for key in ("created_at", "updated_at"):
        stored.pop(key, None)
    if in_token_request():
        stored.pop("created_by", None)
        stored.pop("updated_by", None)
    return stored
