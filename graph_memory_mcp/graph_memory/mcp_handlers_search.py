"""Search handlers for MCP Graph Memory."""

import logging
from typing import Dict, List, Optional

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.cache import hash_query
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.owner_scoped_search import (
    SearchType,
    build_owner_scoped_similarity_query,
    normalize_search_type,
)
from graph_memory_mcp.graph_memory.utils import (
    ensure_text,
    error_response,
    escape_value,
    execute_query,
    format_vecf32,
    load_json,
    mcp_handler,
    normalize_owner_id,
    parse_embedding_value,
    success_response,
)

logger = logging.getLogger(__name__)


def _vector_ann_k(
    limit: int,
    graph_total: int | None,
    config: MCPServerConfig,
) -> int:
    """Size the ANN candidate pool for post_filter search."""
    baseline = max(limit * 2, config.post_filter_ann_k_min)
    if not graph_total or graph_total <= baseline:
        return baseline
    scaled = max(baseline, graph_total // 5)
    return min(scaled, config.post_filter_ann_k_max)


def _count_labeled_nodes(db: FalkorDBClient, node_type: str) -> int | None:
    try:
        result = db.graph.query(f"MATCH (n:{node_type}) RETURN count(n)")
        if result and result.result_set:
            return int(result.result_set[0][0])
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not count %s nodes for ANN sizing: %s", node_type, exc)
    return None


def _rows_to_search_results(result) -> List[Dict]:
    results: List[Dict] = []
    if result and hasattr(result, "result_set"):
        for row in result.result_set:
            results.append(
                {
                    "node_id": str(row[0]),
                    "node_type": row[1],
                    "text": ensure_text(row[2]),
                    "status": ensure_text(row[3]),
                    "created_at": row[4],
                    "metadata": load_json(row[5], {}),
                    "similarity": 1.0 - float(row[6]),
                }
            )
    return results


def _search_nodes_post_filter(
    db: FalkorDBClient,
    config: MCPServerConfig,
    node_type: str,
    embedding: List[float],
    limit: int,
    max_distance: float,
    owner_id: str,
    include_outdated: bool = False,
    status: Optional[str] = None,
) -> List[Dict]:
    """post_filter: global ANN (queryNodes), then owner/status filters."""

    status_clause = ""
    if status:
        status_clause = f" AND node.status = '{escape_value(status)}'"
    elif not include_outdated:
        status_clause = " AND (node.status IS NULL OR node.status = 'active')"

    ann_k = _vector_ann_k(limit, _count_labeled_nodes(db, node_type), config)

    query = f"""
    CALL db.idx.vector.queryNodes('{node_type}', 'embedding', {ann_k}, {format_vecf32(embedding)})
    YIELD node, score
    WHERE score <= {max_distance}
      AND node.owner_id = '{escape_value(owner_id)}'
    """

    query += status_clause

    if node_type == "Fact":
        if status == "active" or (status is None and not include_outdated):
            query += " AND (node.expires_at IS NULL OR node.expires_at > timestamp())"

    query += f"""
    RETURN
        id(node) as node_id,
        '{node_type}' as node_type,
        node.text as text,
        node.status as status,
        node.created_at as created_at,
        node.metadata_str as metadata_str,
        score
    LIMIT {limit}
    """

    return _rows_to_search_results(db.graph.query(query))


def _search_nodes_pre_filter(
    db: FalkorDBClient,
    node_type: str,
    embedding: List[float],
    limit: int,
    max_distance: float,
    owner_id: str,
    include_outdated: bool = False,
    status: Optional[str] = None,
) -> List[Dict]:
    """pre_filter: owner/status filters first, then exact vec.cosineDistance."""
    query = build_owner_scoped_similarity_query(
        node_type=node_type,
        embedding=embedding,
        owner_id=owner_id,
        limit=limit,
        max_distance=max_distance,
        include_outdated=include_outdated,
        status=status,
    )
    return _rows_to_search_results(db.graph.query(query))


def _search_nodes_by_type(
    db: FalkorDBClient,
    config: MCPServerConfig,
    node_type: str,
    embedding: List[float],
    limit: int,
    max_distance: float,
    owner_id: str,
    *,
    search_type: SearchType,
    include_outdated: bool = False,
    status: Optional[str] = None,
) -> List[Dict]:
    if search_type == "pre_filter":
        return _search_nodes_pre_filter(
            db,
            node_type,
            embedding,
            limit,
            max_distance,
            owner_id,
            include_outdated,
            status,
        )
    return _search_nodes_post_filter(
        db,
        config,
        node_type,
        embedding,
        limit,
        max_distance,
        owner_id,
        include_outdated,
        status,
    )


@mcp_handler
def search(
    db: FalkorDBClient,
    config: MCPServerConfig,
    *,
    query: str,
    owner_id: str = "default",
    limit: Optional[int] = None,
    node_types: Optional[List[str]] = None,
    status: Optional[str] = None,
    similarity_threshold: Optional[float] = None,
    include_outdated: bool = False,
    search_type: Optional[str] = None,
) -> Dict:
    """Search for nodes by semantic similarity."""
    owner_id = normalize_owner_id(owner_id)
    try:
        resolved_search_type = normalize_search_type(
            search_type if search_type is not None else config.default_search_type
        )
    except ValueError as exc:
        return error_response(str(exc), code="memory_validation_error")

    cache_key = hash_query(
        query,
        owner_id=owner_id,
        limit=limit,
        node_types=node_types,
        status=status,
        similarity_threshold=similarity_threshold,
        include_outdated=include_outdated,
        search_type=resolved_search_type,
    )

    if cached := db.cache.get_search(cache_key):
        return cached

    limit = limit or config.default_search_limit
    similarity_threshold = (
        similarity_threshold
        if similarity_threshold is not None
        else config.semantic_similarity_threshold
    )

    if node_types is None:
        node_types = ["Fact", "Entity"]
    else:
        node_types = [
            nt.capitalize()
            for nt in node_types
            if nt.capitalize() in ["Fact", "Entity"]
        ]
        if not node_types:
            node_types = ["Fact", "Entity"]

    db.ensure_search_indexes_if_missing()

    embedding = db.get_embedding(query)
    if not embedding:
        return success_response(results=[], facts=[], entities=[])

    max_distance = 1.0 - similarity_threshold
    results: List[Dict] = []

    for node_type in node_types:
        type_results = _search_nodes_by_type(
            db,
            config,
            node_type,
            embedding,
            limit,
            max_distance,
            owner_id,
            search_type=resolved_search_type,
            include_outdated=include_outdated,
            status=status,
        )
        results.extend(type_results)

    results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    results = results[:limit]

    facts = [n for n in results if n.get("node_type") == "Fact"]
    entities = [n for n in results if n.get("node_type") == "Entity"]

    final_response = success_response(results=results, facts=facts, entities=entities)

    db.cache.set_search(cache_key, final_response)

    return final_response


@mcp_handler
def find_similar(
    db: FalkorDBClient,
    config: MCPServerConfig,
    *,
    fact_id: str,
    owner_id: str = "default",
    limit: int = 5,
    similarity_threshold: Optional[float] = None,
) -> Dict:
    """Find similar facts to a given fact."""
    owner_id = normalize_owner_id(owner_id)
    db.ensure_vector_indexes_if_missing()
    similarity_threshold = (
        similarity_threshold
        if similarity_threshold is not None
        else config.semantic_similarity_threshold
    )

    get_query = """
    MATCH (n:Fact)
    WHERE id(n) = $fact_id AND n.owner_id = $owner_id
    RETURN n.embedding as embedding
    """

    result = execute_query(
        db, get_query, {"fact_id": int(fact_id), "owner_id": owner_id}
    )
    if not result:
        return error_response(f"Fact {fact_id} not found", code="memory_not_found")

    embedding = parse_embedding_value(result.result_set[0][0])
    if not embedding:
        return success_response(similar_facts=[])

    max_distance = 1.0 - similarity_threshold

    ann_k = _vector_ann_k(limit + 1, _count_labeled_nodes(db, "Fact"), config)

    similar_query = f"""
    CALL db.idx.vector.queryNodes('Fact', 'embedding', {ann_k}, {format_vecf32(embedding)})
    YIELD node, score
    WHERE score <= {max_distance}
      AND node.owner_id = '{escape_value(owner_id)}'
      AND id(node) <> {int(fact_id)}
    RETURN
        id(node) as node_id,
        node.text as text,
        node.status as status,
        node.created_at as created_at,
        node.metadata_str as metadata_str,
        score
    LIMIT {limit}
    """

    result = db.graph.query(similar_query)

    similar_facts = []
    if result and hasattr(result, "result_set"):
        for row in result.result_set:
            similar_facts.append(
                {
                    "node_id": str(row[0]),
                    "text": ensure_text(row[1]),
                    "status": ensure_text(row[2]),
                    "created_at": row[3],
                    "metadata": load_json(row[4], {}),
                    "similarity": 1.0 - float(row[5]),
                }
            )

    return success_response(similar_facts=similar_facts)
