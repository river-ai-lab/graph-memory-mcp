"""Owner-scoped semantic search query builders (filter-first / exact cosine)."""

from __future__ import annotations

from typing import List, Literal, Optional

from graph_memory_mcp.graph_memory.utils import escape_value, format_vecf32

SearchType = Literal["pre_filter", "post_filter"]


def normalize_search_type(
    value: str | None, *, default: SearchType = "pre_filter"
) -> SearchType:
    """Normalize MCP search_type to pre_filter or post_filter."""
    if value is None or not str(value).strip():
        return default
    normalized = str(value).strip().lower().replace("-", "_")
    if normalized in {"pre_filter", "prefilter", "pre"}:
        return "pre_filter"
    if normalized in {"post_filter", "postfilter", "post"}:
        return "post_filter"
    raise ValueError(
        f"Invalid search_type {value!r}; expected 'pre_filter' or 'post_filter'"
    )


def _property_filter_clauses(
    node_type: str,
    *,
    include_outdated: bool,
    status: Optional[str],
    node_alias: str = "node",
) -> str:
    clauses: list[str] = []
    if status:
        clauses.append(f" AND {node_alias}.status = '{escape_value(status)}'")
    elif not include_outdated:
        clauses.append(
            f" AND ({node_alias}.status IS NULL OR {node_alias}.status = 'active')"
        )

    if node_type == "Fact":
        if status == "active" or (status is None and not include_outdated):
            clauses.append(
                f" AND ({node_alias}.expires_at IS NULL OR {node_alias}.expires_at > timestamp())"
            )
    return "".join(clauses)


def build_owner_scoped_similarity_query(
    *,
    node_type: str,
    embedding: List[float],
    owner_id: str,
    limit: int,
    max_distance: float,
    include_outdated: bool = False,
    status: Optional[str] = None,
    exclude_node_id: Optional[int] = None,
) -> str:
    """Cypher: MATCH owner-scoped nodes, exact vec.cosineDistance, ORDER BY score."""
    property_filters = _property_filter_clauses(
        node_type,
        include_outdated=include_outdated,
        status=status,
    )
    exclude_clause = ""
    if exclude_node_id is not None:
        exclude_clause = f" AND id(node) <> {int(exclude_node_id)}"

    return f"""
    MATCH (node:{node_type})
    WHERE node.owner_id = '{escape_value(owner_id)}'
      AND node.embedding IS NOT NULL
    {property_filters}
    WITH node, vec.cosineDistance(node.embedding, {format_vecf32(embedding)}) AS score
    WHERE score <= {max_distance}{exclude_clause}
    RETURN
        id(node) as node_id,
        '{node_type}' as node_type,
        node.text as text,
        node.status as status,
        node.created_at as created_at,
        node.metadata_str as metadata_str,
        score
    ORDER BY score ASC
    LIMIT {int(limit)}
    """
