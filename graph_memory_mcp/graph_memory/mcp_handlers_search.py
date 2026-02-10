"""Search handlers for MCP Graph Memory."""

import logging
from typing import Any, Dict, List, Optional

from graph_memory_mcp.graph_memory.cache import hash_query
from graph_memory_mcp.graph_memory.database import FalkorDBClient
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


def _search_nodes_by_type(
    db: FalkorDBClient,
    node_type: str,
    embedding: List[float],
    limit: int,
    max_distance: float,
    owner_id: str,
    include_outdated: bool = False,
    status: Optional[str] = None,
) -> List[Dict]:
    """Helper to search nodes of a specific type (Fact/Entity)."""

    query = f"""
    CALL db.idx.vector.queryNodes('{node_type}', 'embedding', {limit * 2}, {format_vecf32(embedding)})
    YIELD node, score
    WHERE score <= {max_distance}
      AND node.owner_id = '{escape_value(owner_id)}'
    """

    # Specific filtering for Facts
    if node_type == "Fact":
        query += " AND (node.expires_at IS NULL OR node.expires_at > timestamp())"

        if not include_outdated:
            query += " AND node.status <> 'outdated'"

        if status:
            query += f" AND node.status = '{escape_value(status)}'"

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

    result = db.graph.query(query)
    results = []

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


@mcp_handler
def search(
    db: FalkorDBClient,
    config: Any,
    *,
    query: str,
    owner_id: str = "default",
    limit: Optional[int] = None,
    node_types: Optional[List[str]] = None,
    status: Optional[str] = None,
    similarity_threshold: Optional[float] = None,
    include_outdated: bool = False,
) -> Dict:
    """Search for nodes by semantic similarity."""
    owner_id = normalize_owner_id(owner_id)

    # Create cache key
    cache_key = hash_query(
        query,
        owner_id=owner_id,
        limit=limit,
        node_types=node_types,
        status=status,
        similarity_threshold=similarity_threshold,
        include_outdated=include_outdated,
    )

    # Check cache
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

    # Get embedding
    embedding = db.get_embedding(query)
    if not embedding:
        return success_response(results=[], facts=[], entities=[])

    max_distance = 1.0 - similarity_threshold
    results = []

    for node_type in node_types:
        type_results = _search_nodes_by_type(
            db,
            node_type,
            embedding,
            limit,
            max_distance,
            owner_id,
            include_outdated,
            status,
        )
        results.extend(type_results)

    # Sort by similarity and limit
    results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    results = results[:limit]

    facts = [n for n in results if n.get("node_type") == "Fact"]
    entities = [n for n in results if n.get("node_type") == "Entity"]

    final_response = success_response(results=results, facts=facts, entities=entities)

    # Cache result
    db.cache.set_search(cache_key, final_response)

    return final_response


@mcp_handler
def find_similar(
    db: FalkorDBClient,
    config: Any,
    *,
    fact_id: str,
    owner_id: str = "default",
    limit: int = 5,
    similarity_threshold: Optional[float] = None,
) -> Dict:
    """Find similar facts to a given fact."""
    owner_id = normalize_owner_id(owner_id)
    similarity_threshold = (
        similarity_threshold
        if similarity_threshold is not None
        else config.semantic_similarity_threshold
    )

    # Get source fact
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

    # Find similar facts
    similar_query = f"""
    CALL db.idx.vector.queryNodes('Fact', 'embedding', {limit + 1}, {format_vecf32(embedding)})
    YIELD node, score
    WHERE score <= {max_distance}
      AND node.owner_id = '{db.escape_value(owner_id)}'
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
