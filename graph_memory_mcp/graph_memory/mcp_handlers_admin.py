"""Admin handlers for MCP Graph Memory (stats, health, summary)."""

import logging
from typing import Any, Dict, Optional

from graph_memory_mcp.graph_memory import mcp_handlers_nodes
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.utils import (
    escape_value,
    mcp_handler,
    normalize_owner_id,
    success_response,
)

logger = logging.getLogger(__name__)


@mcp_handler
def test_connection(db: FalkorDBClient) -> Dict:
    """Test database connection."""
    ok = db.connect()
    return success_response(ready=ok)


def health_check(db: FalkorDBClient, embedding_service: Any) -> Dict:
    """Comprehensive health check."""
    falkordb_ok = False
    embeddings_ok = False
    vector_ok = False

    try:
        health = db.health_check()
        falkordb_ok = bool(health.get("falkordb_connected"))
    except Exception as exc:
        logger.error("health_check: falkordb probe failed: %s", exc)

    try:
        embeddings_ok = (
            embedding_service.ping() if hasattr(embedding_service, "ping") else False
        )
    except Exception as exc:
        logger.error("health_check: embeddings probe failed: %s", exc)

    try:
        vector = db.get_vector_index_status()
        vector_ok = bool(vector.get("Fact")) and bool(vector.get("Entity"))
    except Exception as exc:
        logger.error("health_check: vector index probe failed: %s", exc)

    all_ok = falkordb_ok and embeddings_ok and vector_ok
    if not all_ok:
        falkordb_ok = False
        embeddings_ok = False
        vector_ok = False

    return success_response(
        falkordb=falkordb_ok,
        embeddings=embeddings_ok,
        vector_index=vector_ok,
        cache=db.cache.stats(),
    )


@mcp_handler
def get_stats(db: FalkorDBClient, *, owner_id: str = "default") -> Dict:
    """Get graph statistics."""
    owner_id = normalize_owner_id(owner_id)

    query = f"""
    MATCH (n)
    WHERE n.owner_id = '{escape_value(owner_id)}'
    WITH labels(n)[0] as label, count(n) as count
    RETURN label, count
    """

    result = db.graph.query(query)

    stats = {
        "total_nodes": 0,
        "total_facts": 0,
        "total_entities": 0,
        "active_facts": 0,
        "outdated_facts": 0,
    }

    if result and hasattr(result, "result_set"):
        for row in result.result_set:
            label = row[0]
            count = row[1]
            stats["total_nodes"] += count
            if label == "Fact":
                stats["total_facts"] = count
            elif label == "Entity":
                stats["total_entities"] = count

    # Get fact status breakdown
    status_query = f"""
    MATCH (f:Fact)
    WHERE f.owner_id = '{escape_value(owner_id)}'
    WITH f.status as status, count(f) as count
    RETURN status, count
    """

    result = db.graph.query(status_query)
    if result and hasattr(result, "result_set"):
        for row in result.result_set:
            status = row[0]
            count = row[1]
            if status == "active":
                stats["active_facts"] = count
            elif status == "outdated":
                stats["outdated_facts"] = count

    # Get relation count
    rel_query = f"""
    MATCH (a)-[r]->(b)
    WHERE a.owner_id = '{escape_value(owner_id)}'
      AND b.owner_id = '{escape_value(owner_id)}'
    RETURN count(r) as total_relations
    """

    result = db.graph.query(rel_query)
    if result and hasattr(result, "result_set") and result.result_set:
        stats["total_relations"] = result.result_set[0][0]
    else:
        stats["total_relations"] = 0

    return success_response(stats=stats)


@mcp_handler
def create_summary_fact(
    db: FalkorDBClient,
    config: Any,
    *,
    fact_ids: list,
    summary_text: str,
    owner_id: str = "default",
    metadata: Optional[Dict] = None,
) -> Dict:
    """Create a summary fact from multiple facts."""

    # Create summary fact
    result = mcp_handlers_nodes.create_node(
        db,
        config,
        text=summary_text,
        node_type="Fact",
        owner_id=owner_id,
        metadata={
            **(metadata or {}),
            "is_summary": True,
            "source_count": len(fact_ids),
        },
        status="active",
        auto_link=False,
    )

    if not result.get("success"):
        return result

    summary_node = result.get("node", {})
    summary_id = summary_node.get("node_id")

    # Link to source facts
    from graph_memory_mcp.graph_memory import mcp_handlers_relations

    for fact_id in fact_ids:
        try:
            mcp_handlers_relations.create_relation(
                db,
                from_id=summary_id,
                to_id=str(fact_id),
                relation_type="SUMMARIZES",
                owner_id=owner_id,
            )
        except Exception as link_exc:
            logger.warning("Failed to link summary to fact %s: %s", fact_id, link_exc)

    return success_response(summary=summary_node)
