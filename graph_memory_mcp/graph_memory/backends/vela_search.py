"""Vela (Kuzu) Cypher for owner-scoped semantic search.

Scores are cosine distance, matching Falkor: ``1 - cosine_similarity``.
The Vela 0.12 wheel does not publish a loadable vector extension, so both
pre-filter and ANN paths scan with ``array_cosine_similarity``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from graph_memory_mcp.graph_memory.backends.falkor_search import (
    build_metadata_filter_clauses,
)

_EPOCH = "to_epoch_ms(current_timestamp())"


def _property_filter_clauses(
    node_type: str,
    *,
    include_outdated: bool,
    status: Optional[str],
    node_alias: str = "node",
) -> tuple[str, Dict[str, Any]]:
    clauses: list[str] = []
    params: Dict[str, Any] = {}
    if status:
        clauses.append(f" AND {node_alias}.status = $status")
        params["status"] = status
    elif not include_outdated:
        clauses.append(
            f" AND ({node_alias}.status IS NULL OR {node_alias}.status = 'active')"
        )
    if node_type == "Fact" and (
        status == "active" or (status is None and not include_outdated)
    ):
        clauses.append(
            f" AND ({node_alias}.expires_at IS NULL "
            f"OR {node_alias}.expires_at > {_EPOCH})"
        )
    return "".join(clauses), params


def _distance_query(
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
) -> tuple[str, Dict[str, Any]]:
    property_filters, params = _property_filter_clauses(
        node_type,
        include_outdated=include_outdated,
        status=status,
    )
    meta_clauses, meta_params = build_metadata_filter_clauses(metadata_filter)
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
    {meta_clauses}
    WITH node, 1.0 - array_cosine_similarity(node.embedding, $embedding) AS score
    WHERE score IS NOT NULL AND score <= $max_distance{exclude_clause}
    RETURN
        node.uid,
        '{node_type}',
        node.text,
        node.status,
        node.created_at,
        node.metadata_str,
        score
    ORDER BY score ASC
    LIMIT {int(limit)}
    """
    return query, params


def count_labeled(store: Any, node_type: str, owner_id: str) -> int:
    rows = store.rows(
        f"MATCH (n:{node_type}) WHERE n.owner_id = $owner_id RETURN count(n)",
        {"owner_id": owner_id},
    )
    if not rows:
        return 0
    return int(rows[0][0])


def similarity_rows(store: Any, **kwargs: Any) -> List[List[Any]]:
    if not store.embedding_ready(kwargs["owner_id"]):
        return []
    query, params = _distance_query(**kwargs)
    return store.rows(query, params)


def ann_rows(
    store: Any,
    *,
    ann_k: int,
    limit: int,
    **kwargs: Any,
) -> List[List[Any]]:
    """Exact cosine scan. ``ann_k`` is ignored; the distance filter is exact."""
    del ann_k
    return similarity_rows(store, limit=limit, **kwargs)


def fact_embedding(store: Any, fact_id: str, owner_id: str) -> tuple[bool, Any]:
    if not store.embedding_ready(owner_id):
        rows = store.rows(
            """
            MATCH (n:Fact)
            WHERE n.uid = $fact_id AND n.owner_id = $owner_id
            RETURN n.uid
            """,
            {"fact_id": fact_id, "owner_id": owner_id},
        )
        if not rows:
            return False, None
        return True, None
    rows = store.rows(
        """
        MATCH (n:Fact)
        WHERE n.uid = $fact_id AND n.owner_id = $owner_id
        RETURN n.embedding
        """,
        {"fact_id": fact_id, "owner_id": owner_id},
    )
    if not rows:
        return False, None
    return True, rows[0][0]
