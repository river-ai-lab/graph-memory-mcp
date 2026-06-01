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
    normalize_unix_ms,
    success_response,
    validate_inputs,
)

logger = logging.getLogger(__name__)


def _node_return_fields(alias: str = "n") -> str:
    """Return a consistent node projection for reads and mutation responses."""
    return f"""
        id({alias}) as node_id,
        labels({alias})[0] as node_type,
        {alias}.text as text,
        {alias}.description as description,
        {alias}.status as status,
        {alias}.created_at as created_at,
        {alias}.updated_at as updated_at,
        {alias}.metadata_str as metadata_str,
        {alias}.shared_with_ids as shared_with_ids,
        {alias}.ttl_days as ttl_days,
        {alias}.expires_at as expires_at,
        {alias}.type as entity_type,
        {alias}.source_str as source_str
    """


def _node_from_row(row: List[Any]) -> Dict[str, Any]:
    """Build the public node payload from a projected DB row."""
    source = load_json(row[12], None)
    node = {
        "node_id": str(row[0]),
        "node_type": row[1],
        "text": ensure_text(row[2]),
        "status": ensure_text(row[4]),
        "created_at": row[5],
        "metadata": load_json(row[7], {}),
        "ttl_days": row[9],
        "expires_at": row[10],
        "type": ensure_text(row[11]) if row[11] else None,
    }

    node.update(
        {
            k: v
            for k, v in [
                ("description", ensure_text(row[3]) if row[3] else None),
                ("updated_at", row[6]),
                ("shared_with_ids", row[8]),
                ("source", source),
            ]
            if v is not None and v != []
        }
    )
    return node


def _normalize_source(source: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Normalize source payload while keeping the MCP-facing schema compact."""
    if source is None:
        return None
    if not isinstance(source, dict):
        raise ValueError("source must be an object")

    normalized = dict(source)

    for key in ("ref", "type", "uri", "content_hash"):
        value = ensure_text(source.get(key))
        if value is None:
            normalized.pop(key, None)
            continue
        value = value.strip()
        if value:
            normalized[key] = value
        else:
            normalized.pop(key, None)

    updated_at = normalize_unix_ms(source.get("updated_at"))
    if updated_at is not None:
        normalized["updated_at"] = updated_at
    else:
        normalized.pop("updated_at", None)

    version = source.get("version")
    if isinstance(version, int) and version >= 1:
        normalized["version"] = version
    else:
        normalized.pop("version", None)

    return normalized or None


def _source_properties(source: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Flatten source payload into DB-friendly properties while exposing one MCP field."""
    normalized = _normalize_source(source)
    source_ref = ensure_text((normalized or {}).get("ref"))
    source_type = ensure_text((normalized or {}).get("type"))
    source_uri = ensure_text((normalized or {}).get("uri"))
    content_hash = ensure_text((normalized or {}).get("content_hash"))
    source_updated_at = normalize_unix_ms((normalized or {}).get("updated_at"))

    return {
        "source": normalized,
        "source_str": dump_json(normalized) if normalized is not None else None,
        "source_ref": source_ref,
        "source_type": source_type,
        "source_uri": source_uri,
        "content_hash": content_hash,
        "source_updated_at": source_updated_at,
    }


@mcp_handler
def create_node(
    db: FalkorDBClient,
    config: Any,
    *,
    text: str,
    description: Optional[str] = None,
    node_type: Literal["Fact", "Entity"] = "Fact",
    owner_id: str = "default",
    shared_with_ids: Optional[List[str]] = None,
    collection_id: Optional[str] = None,
    metadata: Optional[Dict] = None,
    source: Optional[Dict] = None,
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
    metadata_str = dump_json(metadata or {})  # Maps must be JSON strings in FalkorDB
    source_props = _source_properties(source)

    # Add entity_type for Entity nodes
    type_prop = ""
    if node_type == "Entity" and entity_type:
        type_prop = ", type: $entity_type"

    query = f"""
    CREATE (n:{node_type} {{
        owner_id: $owner_id,
        text: $text,
        description: $description,
        embedding: {format_vecf32(embedding)},
        status: $status,
        created_at: timestamp(),
        updated_at: timestamp(),
        metadata_str: $metadata_str,
        shared_with_ids: $shared_with_ids,
        ttl_days: $ttl_days,
        expires_at: $expires_at,
        last_dedup_at: NULL,
        source_str: $source_str,
        source_ref: $source_ref,
        source_type: $source_type,
        source_uri: $source_uri,
        content_hash: $content_hash,
        source_updated_at: $source_updated_at{type_prop}
    }})
    RETURN {_node_return_fields()}
    """

    params = {
        "owner_id": owner_id,
        "text": text,
        "description": description,
        "status": status or "active",
        "metadata_str": metadata_str,
        "shared_with_ids": shared_with_ids or [],
        "ttl_days": ttl_days,
        "expires_at": expires_at,
    }
    params.update(
        {
            "source_str": source_props["source_str"],
            "source_ref": source_props["source_ref"],
            "source_type": source_props["source_type"],
            "source_uri": source_props["source_uri"],
            "content_hash": source_props["content_hash"],
            "source_updated_at": source_props["source_updated_at"],
        }
    )

    if node_type == "Entity" and entity_type:
        params["entity_type"] = entity_type

    result = execute_query(db, query, params)
    if not result:
        return error_response("Failed to create node", code="memory_service_error")

    node = _node_from_row(result.result_set[0])
    node_id = node["node_id"]

    # Add to collection if specified (extended)
    if collection_id:
        try:
            _add_to_collection(db, node_id, collection_id, owner_id)
        except Exception as exc:
            logger.warning(
                "Failed to add node %s to collection %s: %s",
                node_id,
                collection_id,
                exc,
            )

    # Auto-link Facts to Entities
    if node_type == "Fact" and auto_link:
        threshold = (
            semantic_threshold
            if semantic_threshold is not None
            else config.auto_linking_semantic_threshold
        )
        try:
            _create_auto_links(
                db,
                node_id=node_id,
                threshold=threshold,
                owner_id=owner_id,
                embedding=embedding,
                fact_text=text,
            )
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

    return success_response(node=node)


@mcp_handler
def upsert_node(
    db: FalkorDBClient,
    config: Any,
    *,
    text: str,
    description: Optional[str] = None,
    node_type: Literal["Fact", "Entity"] = "Fact",
    owner_id: str = "default",
    metadata: Optional[Dict] = None,
    source: Optional[Dict] = None,
    status: Optional[Literal["active", "outdated", "archived"]] = None,
    ttl_days: Optional[float] = None,
    versioning: bool = False,
    entity_type: Optional[str] = None,
    auto_link: bool = True,
    semantic_threshold: Optional[float] = None,
    links: Optional[List[Dict]] = None,
) -> Dict:
    """Create or update a node using source.ref as the stable sync key."""
    if source is None:
        return error_response(
            "source is required for upsert_node", code="memory_validation_error"
        )
    if error := validate_inputs(locals(), config):
        return error_response(error, code="memory_validation_error")

    owner_id = normalize_owner_id(owner_id)
    source_props = _source_properties(source)
    source_ref = ensure_text((source_props["source"] or {}).get("ref"))
    if not source_ref:
        return error_response(
            "source.ref is required for upsert_node",
            code="memory_validation_error",
        )

    upsert_source = dict(source_props["source"] or {})
    existing = _get_node_by_source_ref(
        db,
        owner_id=owner_id,
        node_type=node_type,
        source_ref=source_ref,
    )
    if existing is None:
        if versioning and "version" not in upsert_source:
            upsert_source["version"] = 1
        result = create_node(
            db,
            config,
            text=text,
            description=description,
            node_type=node_type,
            owner_id=owner_id,
            metadata=metadata,
            source=upsert_source,
            status=status,
            ttl_days=ttl_days,
            entity_type=entity_type,
            auto_link=auto_link,
            semantic_threshold=semantic_threshold,
            links=links,
        )
        if not result.get("success"):
            return result
        return success_response(node=result["node"], operation="created")

    result = update_node(
        db,
        node_id=existing["node_id"],
        owner_id=owner_id,
        text=text,
        description=description,
        metadata=metadata,
        source=upsert_source,
        status=status,
        ttl_days=ttl_days,
        entity_type=entity_type,
        versioning=versioning,
    )
    if not result.get("success"):
        return result

    return success_response(node=result["node"], operation="updated")


@mcp_handler
def get_node(db: FalkorDBClient, *, node_id: str, owner_id: str = "default") -> Dict:
    """Get a node by ID."""
    owner_id = normalize_owner_id(owner_id)

    query = """
    MATCH (n)
    WHERE id(n) = $node_id AND n.owner_id = $owner_id
    RETURN
    """
    query += _node_return_fields()

    result = execute_query(db, query, {"node_id": int(node_id), "owner_id": owner_id})
    if not result:
        return error_response(f"Node {node_id} not found", code="memory_not_found")

    return success_response(node=_node_from_row(result.result_set[0]))


@mcp_handler
def update_node(
    db: FalkorDBClient,
    *,
    node_id: str,
    owner_id: str = "default",
    text: Optional[str] = None,
    description: Optional[str] = None,
    shared_with_ids: Optional[List[str]] = None,
    metadata: Optional[Dict] = None,
    source: Optional[Dict] = None,
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
            description: n.description,
            metadata_str: n.metadata_str,
            source_str: n.source_str,
            shared_with_ids: n.shared_with_ids,
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
    set_clauses = ["n.updated_at = timestamp()"]
    params = {"node_id": int(node_id), "owner_id": owner_id}

    if text is not None:
        set_clauses.append("n.text = $text")
        params["text"] = text
        # Update embedding
        embedding = db.get_embedding(text)
        set_clauses.append(f"n.embedding = {format_vecf32(embedding)}")

    if description is not None:
        set_clauses.append("n.description = $description")
        params["description"] = description

    if shared_with_ids is not None:
        set_clauses.append("n.shared_with_ids = $shared_with_ids")
        params["shared_with_ids"] = shared_with_ids

    if metadata is not None:
        base_meta = node.get("metadata", {})
        merged_metadata = {**base_meta, **metadata}
        set_clauses.append("n.metadata_str = $metadata_str")
        params["metadata_str"] = dump_json(merged_metadata)

    next_source = None
    if source is not None:
        next_source = dict(source)
    elif versioning:
        next_source = dict(node.get("source") or {})

    if (
        versioning
        and next_source is not None
        and (source is None or "version" not in next_source)
    ):
        current_version = (node.get("source") or {}).get("version")
        if not isinstance(current_version, int) or current_version < 1:
            current_version = 0
        next_source["version"] = current_version + 1

    if next_source is not None:
        source_props = _source_properties(next_source)
        set_clauses.extend(
            [
                "n.source_str = $source_str",
                "n.source_ref = $source_ref",
                "n.source_type = $source_type",
                "n.source_uri = $source_uri",
                "n.content_hash = $content_hash",
                "n.source_updated_at = $source_updated_at",
            ]
        )
        params.update(
            {
                "source_str": source_props["source_str"],
                "source_ref": source_props["source_ref"],
                "source_type": source_props["source_type"],
                "source_uri": source_props["source_uri"],
                "content_hash": source_props["content_hash"],
                "source_updated_at": source_props["source_updated_at"],
            }
        )

    if status is not None:
        set_clauses.append("n.status = $status")
        params["status"] = status

    if ttl_days is not None:
        set_clauses.append("n.ttl_days = $ttl_days")
        params["ttl_days"] = ttl_days
        if ttl_days > 0:
            expires_at = int(time.time() * 1000) + int(ttl_days * 24 * 3600 * 1000)
            set_clauses.append("n.expires_at = $expires_at")
            params["expires_at"] = expires_at
        else:
            set_clauses.append("n.expires_at = NULL")

    if entity_type is not None and node_type == "Entity":
        set_clauses.append("n.type = $entity_type")
        params["entity_type"] = entity_type

    if len(set_clauses) == 1:  # Only updated_at
        return get_node(db, node_id=node_id, owner_id=owner_id)

    query = f"""
    MATCH (n)
    WHERE id(n) = $node_id AND n.owner_id = $owner_id
    SET {', '.join(set_clauses)}
    RETURN {_node_return_fields()}
    """

    # Execute update
    result = execute_query(db, query, params)
    if not result:
        return error_response("Failed to update node", code="memory_service_error")

    # Invalidate search cache
    db.cache.invalidate_search()

    return success_response(node=_node_from_row(result.result_set[0]))


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
        v.source_str as source_str,
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
                    "source": load_json(row[3], None),
                    "status": ensure_text(row[4]),
                    "ttl_days": row[5],
                    "version_timestamp": row[6],
                    "original_created_at": row[7],
                }
            )

    return success_response(versions=versions, count=len(versions))


# ====================
# Inner Functions
# ====================


def _get_node_by_source_ref(
    db: FalkorDBClient,
    *,
    owner_id: str,
    node_type: Literal["Fact", "Entity"],
    source_ref: str,
) -> Optional[Dict[str, Any]]:
    """Load a node by same-owner source.ref, used for idempotent upserts."""
    query = f"""
    MATCH (n:{node_type})
    WHERE n.owner_id = $owner_id AND n.source_ref = $source_ref
    RETURN {_node_return_fields()}
    LIMIT 1
    """

    result = execute_query(
        db,
        query,
        {"owner_id": normalize_owner_id(owner_id), "source_ref": source_ref},
    )
    if not result:
        return None
    return _node_from_row(result.result_set[0])


def _create_auto_links(
    db: FalkorDBClient,
    *,
    node_id: str,
    threshold: float,
    owner_id: str,
    embedding: Optional[List[float]] = None,
    fact_text: Optional[str] = None,
) -> None:
    """Auto-link a Fact to similar Entities."""
    try:
        if not embedding and fact_text is not None:
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
        WHERE id(f) = {int(node_id)} AND id(e) = id(node)
        MERGE (f)-[r:MENTIONS]->(e)
        ON CREATE SET r.created_at = timestamp(), r.auto_linked = true
        RETURN count(r) as links_created
        """

        db.graph.query(query)
    except Exception as e:
        logger.warning("Auto-link failed: %s", e)


def _add_to_collection(
    db: FalkorDBClient, node_id: str, collection_id: str, owner_id: str
) -> None:
    """Add a node to a collection (extended functionality).

    Creates a CONTAINS relationship from Collection to Node.
    """
    query = """
    MATCH (c:Collection), (n)
    WHERE id(c) = $collection_id AND id(n) = $node_id
      AND c.owner_id = $owner_id AND n.owner_id = $owner_id
    MERGE (c)-[r:CONTAINS]->(n)
    ON CREATE SET r.created_at = timestamp()
    RETURN count(r) as created
    """

    params = {
        "collection_id": int(collection_id),
        "node_id": int(node_id),
        "owner_id": owner_id,
    }

    result = db.graph.query(query, params=params)
    if not result or not result.result_set:
        raise ValueError(f"Failed to add node {node_id} to collection {collection_id}")
