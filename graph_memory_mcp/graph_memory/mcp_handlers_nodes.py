"""Node handlers for MCP Graph Memory (Fact/Entity CRUD)."""

import logging
import time
from typing import Any, Dict, List, Literal, Optional

from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.mcp_handlers_relations import create_relation
from graph_memory_mcp.graph_memory.utils import (
    dump_json,
    ensure_text,
    error_response,
    escape_value,
    execute_query,
    format_vecf32,
    load_json,
    mcp_handler,
    normalize_owner_id,
    success_response,
    validate_inputs,
)

logger = logging.getLogger(__name__)


@mcp_handler
def create_node(
    db: FalkorDBClient,
    config: Any,
    *,
    text: str,
    node_type: Literal["Fact", "Entity"] = "Fact",
    owner_id: str = "default",
    metadata: Optional[Dict] = None,
    status: Optional[Literal["active", "outdated", "archived"]] = None,
    ttl_days: Optional[float] = None,
    entity_type: Optional[str] = None,
    auto_link: bool = True,
    semantic_threshold: Optional[float] = None,
    links: Optional[List[Dict]] = None,
) -> Dict:
    """Create a Fact or Entity node."""
    if error := validate_inputs(locals(), config):
        return error_response(error, code="memory_validation_error")

    owner_id = normalize_owner_id(owner_id)
    embedding = db.get_embedding(text)

    # Calculate expires_at
    expires_at = None
    if ttl_days is not None and ttl_days > 0:
        expires_at = int(time.time() * 1000) + int(ttl_days * 24 * 3600 * 1000)

    # Create node
    metadata_str = dump_json(metadata or {})

    # Add entity_type for Entity nodes
    type_prop = ""
    if node_type == "Entity" and entity_type:
        type_prop = ", type: $entity_type"

    query = f"""
    CREATE (n:{node_type} {{
        owner_id: $owner_id,
        text: $text,
        embedding: {format_vecf32(embedding)},
        status: $status,
        created_at: timestamp(),
        metadata_str: $metadata_str,
        ttl_days: $ttl_days,
        expires_at: $expires_at,
        last_dedup_at: NULL{type_prop}
    }})
    RETURN id(n) as node_id
    """

    params = {
        "owner_id": owner_id,
        "text": text,
        "status": status or "active",
        "metadata_str": metadata_str,
        "ttl_days": ttl_days,
        "expires_at": expires_at,
    }

    if node_type == "Entity" and entity_type:
        params["entity_type"] = entity_type

    result = execute_query(db, query, params)
    if not result:
        return error_response("Failed to create node", code="memory_service_error")

    node_id = str(result.result_set[0][0])

    # Auto-link Facts to Entities
    if node_type == "Fact" and auto_link:
        threshold = (
            semantic_threshold
            if semantic_threshold is not None
            else config.auto_linking_semantic_threshold
        )
        try:
            _create_auto_links(db, node_id, text, threshold, owner_id)
        except Exception as exc:
            logger.warning("Auto-link failed for node_id=%s: %s", node_id, exc)

    # Explicit links
    if links:
        for link in links:
            if not isinstance(link, dict):
                continue
            to_id = link.get("node_id") or link.get("to_id")
            rel_type = link.get("relation_type") or link.get("type")
            if to_id and rel_type:
                try:
                    props = link.get("metadata") or link.get("properties")
                    create_relation(
                        db,
                        from_id=node_id,
                        to_id=str(to_id),
                        relation_type=str(rel_type),
                        properties=props,
                        owner_id=owner_id,
                    )
                except Exception as link_exc:
                    logger.warning("Explicit link failed: %s", link_exc)

    db.cache.invalidate_search()

    return success_response(
        node=get_node(db, node_id=node_id, owner_id=owner_id)["node"]
    )


@mcp_handler
def get_node(db: FalkorDBClient, *, node_id: str, owner_id: str = "default") -> Dict:
    """Get a node by ID."""
    owner_id = normalize_owner_id(owner_id)

    query = """
    MATCH (n)
    WHERE id(n) = $node_id AND n.owner_id = $owner_id
    RETURN
        id(n) as node_id,
        labels(n)[0] as node_type,
        n.text as text,
        n.status as status,
        n.created_at as created_at,
        n.metadata_str as metadata_str,
        n.ttl_days as ttl_days,
        n.expires_at as expires_at,
        n.type as entity_type,
        n.embedding as embedding
    """

    result = execute_query(db, query, {"node_id": int(node_id), "owner_id": owner_id})
    if not result:
        return error_response(f"Node {node_id} not found", code="memory_not_found")

    row = result.result_set[0]
    node = {
        "node_id": str(row[0]),
        "node_type": row[1],
        "text": ensure_text(row[2]),
        "status": ensure_text(row[3]),
        "created_at": row[4],
        "metadata": load_json(row[5], {}),
        "ttl_days": row[6],
        "expires_at": row[7],
    }

    # Add entity_type for Entity nodes
    if row[1] == "Entity" and row[8]:
        node["type"] = ensure_text(row[8])

    # Remove embedding from response
    return success_response(node=node)


@mcp_handler
def update_node(
    db: FalkorDBClient,
    *,
    node_id: str,
    owner_id: str = "default",
    text: Optional[str] = None,
    metadata: Optional[Dict] = None,
    status: Optional[Literal["active", "outdated", "archived"]] = None,
    ttl_days: Optional[float] = None,
    entity_type: Optional[str] = None,
    versioning: bool = False,
) -> Dict:
    """Update a Fact or Entity node."""
    owner_id = normalize_owner_id(owner_id)

    if error := validate_inputs(locals(), db.config if hasattr(db, "config") else None):
        return error_response(error, code="memory_validation_error")

    # Get existing node
    existing = get_node(db, node_id=node_id, owner_id=owner_id)
    if not existing.get("success"):
        return existing

    node = existing["node"]
    node_type = node.get("node_type")

    # Create version snapshot if versioning enabled
    if versioning and node_type == "Fact":
        version_query = """
        MATCH (n:Fact)
        WHERE id(n) = $node_id AND n.owner_id = $owner_id
        CREATE (v:FactVersion {
            fact_id: id(n),
            owner_id: n.owner_id,
            text: n.text,
            metadata_str: n.metadata_str,
            status: n.status,
            ttl_days: n.ttl_days,
            expires_at: n.expires_at,
            version_timestamp: timestamp(),
            original_created_at: n.created_at
        })
        RETURN id(v) as version_id
        """
        db.graph.query(
            version_query, params={"node_id": int(node_id), "owner_id": owner_id}
        )

    # Build SET clauses
    set_clauses = []
    params = {"node_id": int(node_id), "owner_id": owner_id}

    if text is not None:
        set_clauses.append("n.text = $text")
        params["text"] = text
        # Update embedding
        embedding = db.get_embedding(text)
        set_clauses.append(f"n.embedding = {format_vecf32(embedding)}")

    if metadata is not None:
        base_meta = node.get("metadata", {})
        merged_metadata = {**base_meta, **metadata}
        set_clauses.append("n.metadata_str = $metadata_str")
        params["metadata_str"] = dump_json(merged_metadata)

    if status is not None:
        set_clauses.append("n.status = $status")
        params["status"] = status

    if ttl_days is not None:
        set_clauses.append("n.ttl_days = $ttl_days")
        params["ttl_days"] = ttl_days
        # Recalculate expires_at
        expires_at = int(time.time() * 1000) + int(ttl_days * 24 * 3600 * 1000)
        set_clauses.append("n.expires_at = $expires_at")
        params["expires_at"] = expires_at

    if entity_type is not None and node_type == "Entity":
        set_clauses.append("n.type = $entity_type")
        params["entity_type"] = entity_type

    if not set_clauses:
        return get_node(db, node_id=node_id, owner_id=owner_id)

    query = f"""
    MATCH (n)
    WHERE id(n) = $node_id AND n.owner_id = $owner_id
    SET {', '.join(set_clauses)}
    RETURN id(n)
    """

    # Execute update
    db.graph.query(query, params=params)

    # Invalidate search cache
    db.cache.invalidate_search()

    return success_response(
        node=get_node(db, node_id=node_id, owner_id=owner_id)["node"]
    )


@mcp_handler
def delete_node(db: FalkorDBClient, *, node_id: str, owner_id: str = "default") -> Dict:
    """Delete a node and all its relationships."""
    owner_id = normalize_owner_id(owner_id)

    query = """
    MATCH (n)
    WHERE id(n) = $node_id AND n.owner_id = $owner_id
    DETACH DELETE n
    RETURN count(n) as deleted
    """

    result = execute_query(db, query, {"node_id": int(node_id), "owner_id": owner_id})
    if not result:
        return error_response("Failed to delete node", code="memory_service_error")

    deleted = result.result_set[0][0]
    if deleted == 0:
        return error_response(f"Node {node_id} not found", code="memory_not_found")

    db.cache.invalidate_search()

    return success_response()


@mcp_handler
def mark_outdated(
    db: FalkorDBClient,
    *,
    fact_id: str,
    reason: Optional[str] = None,
    owner_id: str = "default",
) -> Dict:
    """Mark a fact as outdated."""
    meta = {"status_reason": reason} if reason else None
    return update_node(
        db, node_id=fact_id, owner_id=owner_id, status="outdated", metadata=meta
    )


@mcp_handler
def get_node_change_history(
    db: FalkorDBClient,
    *,
    node_id: str,
    owner_id: str = "default",
) -> Dict:
    """Get change history for a node."""
    owner_id = normalize_owner_id(owner_id)

    # Query for version history
    query = """
    MATCH (v:FactVersion)
    WHERE v.fact_id = $node_id AND v.owner_id = $owner_id
    RETURN
        id(v) as version_id,
        v.text as text,
        v.metadata_str as metadata_str,
        v.status as status,
        v.ttl_days as ttl_days,
        v.version_timestamp as version_timestamp,
        v.original_created_at as original_created_at
    ORDER BY v.version_timestamp DESC
    """

    result = db.graph.query(
        query, params={"node_id": int(node_id), "owner_id": owner_id}
    )

    versions = []
    if result and hasattr(result, "result_set"):
        for row in result.result_set:
            versions.append(
                {
                    "version_id": str(row[0]),
                    "text": ensure_text(row[1]),
                    "metadata": load_json(row[2], {}),
                    "status": ensure_text(row[3]),
                    "ttl_days": row[4],
                    "version_timestamp": row[5],
                    "original_created_at": row[6],
                }
            )

    return success_response(versions=versions, count=len(versions))


# ====================
# Inner Functions
# ====================


def _create_auto_links(
    db: FalkorDBClient,
    fact_id: str,
    fact_text: str,
    threshold: float,
    owner_id: str,
) -> None:
    """Auto-link a Fact to similar Entities."""
    try:
        embedding = db.get_embedding(fact_text)
        if not embedding:
            return

        max_distance = 1.0 - threshold

        query = f"""
        CALL db.idx.vector.queryNodes('Entity', 'embedding', 10, {format_vecf32(embedding)})
        YIELD node, score
        WHERE score <= {max_distance}
          AND node.owner_id = '{escape_value(owner_id)}'
        WITH node
        MATCH (f), (e)
        WHERE id(f) = {int(fact_id)} AND id(e) = id(node)
        MERGE (f)-[r:MENTIONS]->(e)
        ON CREATE SET r.created_at = timestamp(), r.auto_linked = true
        RETURN count(r) as links_created
        """

        db.graph.query(query)
    except Exception as e:
        logger.warning("Auto-link failed: %s", e)
