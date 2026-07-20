"""Owner-scoped semantic search query builders (filter-first / exact cosine)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

SearchType = Literal["pre_filter", "post_filter"]

_METADATA_FILTER_KEYS = frozenset(
    {"type", "tags", "confidence_min", "project", "created_by"}
)


def build_metadata_filter_clauses(
    metadata_filter: Optional[Dict[str, Any]],
    *,
    node_alias: str = "node",
    param_prefix: str = "mf_",
) -> Tuple[str, Dict[str, Any]]:
    """Cypher clauses over promoted metadata properties.

    Supported: `project` / `created_by` / `type` (equality), `tags`
    (membership, all must be present), `confidence_min` (>=).
    Raises ValueError on unsupported keys. Runs natively in FalkorDB — no
    client-side filtering.
    """
    if not metadata_filter:
        return "", {}
    unknown = set(metadata_filter) - _METADATA_FILTER_KEYS
    if unknown:
        raise ValueError(
            f"Unsupported metadata_filter keys: {sorted(unknown)}; "
            f"allowed: {sorted(_METADATA_FILTER_KEYS)}"
        )
    clauses: list[str] = []
    params: Dict[str, Any] = {}
    for key, prop in (
        ("project", "project"),
        ("created_by", "created_by"),
        ("type", "meta_type"),
    ):
        if (value := metadata_filter.get(key)) is not None:
            clauses.append(f" AND {node_alias}.{prop} = ${param_prefix}{key}")
            params[f"{param_prefix}{key}"] = str(value)
    tags = metadata_filter.get("tags")
    if tags is not None:
        tags = [tags] if isinstance(tags, str) else list(tags)
        for i, tag in enumerate(tags):
            clauses.append(f" AND ${param_prefix}tag{i} IN {node_alias}.tags")
            params[f"{param_prefix}tag{i}"] = str(tag)
    if (conf_min := metadata_filter.get("confidence_min")) is not None:
        clauses.append(f" AND {node_alias}.confidence >= ${param_prefix}conf")
        params[f"{param_prefix}conf"] = float(conf_min)
    return "".join(clauses), params


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
) -> Tuple[str, Dict[str, Any]]:
    clauses: list[str] = []
    params: Dict[str, Any] = {}
    if status:
        clauses.append(f" AND {node_alias}.status = $status")
        params["status"] = status
    elif not include_outdated:
        clauses.append(
            f" AND ({node_alias}.status IS NULL OR {node_alias}.status = 'active')"
        )

    if node_type == "Fact":
        if status == "active" or (status is None and not include_outdated):
            clauses.append(
                f" AND ({node_alias}.expires_at IS NULL OR {node_alias}.expires_at > timestamp())"
            )
    return "".join(clauses), params


def build_owner_scoped_similarity_query(
    *,
    node_type: str,
    embedding: List[float],
    owner_id: str,
    limit: int,
    max_distance: float,
    include_outdated: bool = False,
    status: Optional[str] = None,
    exclude_node_id: Optional[str] = None,
    metadata_filter: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Cypher + params: owner-scoped nodes, exact vec.cosineDistance, ORDER BY score."""
    property_filters, params = _property_filter_clauses(
        node_type,
        include_outdated=include_outdated,
        status=status,
    )
    meta_clauses, meta_params = build_metadata_filter_clauses(metadata_filter)
    property_filters += meta_clauses
    params.update(meta_params)
    exclude_clause = ""
    if exclude_node_id is not None:
        exclude_clause = " AND node.uid <> $exclude_uid"
        params["exclude_uid"] = str(exclude_node_id)

    params.update(
        {
            "owner_id": owner_id,
            "embedding": [float(v) for v in embedding],
            "max_distance": float(max_distance),
        }
    )

    query = f"""
    MATCH (node:{node_type})
    WHERE node.owner_id = $owner_id
      AND node.embedding IS NOT NULL
    {property_filters}
    WITH node, vec.cosineDistance(node.embedding, vecf32($embedding)) AS score
    WHERE score <= $max_distance{exclude_clause}
    RETURN
        node.uid as node_id,
        '{node_type}' as node_type,
        node.text as text,
        node.status as status,
        node.created_at as created_at,
        node.metadata_str as metadata_str,
        score
    ORDER BY score ASC
    LIMIT {int(limit)}
    """
    return query, params
