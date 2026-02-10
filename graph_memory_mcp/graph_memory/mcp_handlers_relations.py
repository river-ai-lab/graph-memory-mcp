"""Relation and triplet handlers for MCP Graph Memory."""

import logging
from typing import Dict, Optional

from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.utils import (
    ensure_text,
    error_response,
    escape_value,
    execute_query,
    format_vecf32,
    mcp_handler,
    normalize_owner_id,
    normalize_predicate_type,
    success_response,
    validate_inputs,
)

logger = logging.getLogger(__name__)


@mcp_handler
def create_relation(
    db: FalkorDBClient,
    *,
    from_id: str,
    to_id: str,
    relation_type: str,
    properties: Optional[Dict] = None,
    owner_id: str = "default",
) -> Dict:
    """Create a relation between two nodes."""
    owner_id = normalize_owner_id(owner_id)
    if error := validate_inputs(locals(), None):
        return error_response(error, code="memory_validation_error")

    rel_type = normalize_predicate_type(relation_type)

    props_str = ""
    if properties:
        props_str = ", " + ", ".join(f"r.{k} = ${k}" for k in properties.keys())

    query = f"""
    MATCH (a), (b)
    WHERE id(a) = $from_id AND id(b) = $to_id
        AND a.owner_id = $owner_id AND b.owner_id = $owner_id
    MERGE (a)-[r:{rel_type}]->(b)
    ON CREATE SET r.created_at = timestamp(){props_str}
    RETURN id(r) as rel_id
    """

    params = {
        "from_id": int(from_id),
        "to_id": int(to_id),
        "owner_id": owner_id,
    }
    if properties:
        params.update(properties)

    result = execute_query(db, query, params)
    if not result:
        return error_response("Failed to create relation", code="memory_service_error")

    db.cache.invalidate_search()

    return success_response(relation_type=rel_type)


@mcp_handler
def create_triplet(
    db: FalkorDBClient,
    *,
    subject: str,
    predicate: str,
    object_value: str,
    metadata: Optional[Dict] = None,
    fact_id: Optional[str] = None,
    owner_id: str = "default",
) -> Dict:
    """Create a subject-predicate-object triplet."""
    owner_id = normalize_owner_id(owner_id)

    # Create or get subject entity
    subj_emb = db.get_embedding(subject)
    obj_emb = db.get_embedding(object_value)

    query = f"""
    MERGE (s:Entity {{text: $subject, owner_id: $owner_id}})
    ON CREATE SET
        s.created_at = timestamp(),
        s.embedding = {format_vecf32(subj_emb)},
        s.status = 'active',
        s.metadata_str = '{{}}'
    MERGE (o:Entity {{text: $object, owner_id: $owner_id}})
    ON CREATE SET
        o.created_at = timestamp(),
        o.embedding = {format_vecf32(obj_emb)},
        o.status = 'active',
        o.metadata_str = '{{}}'
    MERGE (s)-[r:{normalize_predicate_type(predicate)}]->(o)
    ON CREATE SET r.created_at = timestamp()
    RETURN id(s) as subject_id, id(o) as object_id, id(r) as relation_id
    """

    params = {
        "subject": subject,
        "object": object_value,
        "owner_id": owner_id,
    }

    result = execute_query(db, query, params)
    if not result:
        return error_response("Failed to create triplet", code="memory_service_error")

    row = result.result_set[0]
    triplet = {
        "subject_id": str(row[0]),
        "object_id": str(row[1]),
        "relation_id": str(row[2]),
        "subject": subject,
        "predicate": predicate,
        "object": object_value,
    }

    # Link to fact if provided
    if fact_id:
        link_query = """
        MATCH (f:Fact), (s:Entity)
        WHERE id(f) = $fact_id AND id(s) = $subject_id
            AND f.owner_id = $owner_id AND s.owner_id = $owner_id
        MERGE (f)-[r:EXTRACTED_FROM]->(s)
        ON CREATE SET r.created_at = timestamp()
        """
        db.graph.query(
            link_query,
            params={
                "fact_id": int(fact_id),
                "subject_id": int(row[0]),
                "owner_id": owner_id,
            },
        )

    db.cache.invalidate_search()

    return success_response(triplet=triplet)


@mcp_handler
def search_triplets(
    db: FalkorDBClient,
    *,
    subject: Optional[str] = None,
    predicate: Optional[str] = None,
    object_value: Optional[str] = None,
    owner_id: str = "default",
    limit: int = 10,
) -> Dict:
    """Search for triplets matching the pattern."""
    owner_id = normalize_owner_id(owner_id)

    where_clauses = [f"s.owner_id = '{escape_value(owner_id)}'"]

    if subject:
        where_clauses.append(f"s.text = '{escape_value(subject)}'")
    if object_value:
        where_clauses.append(f"o.text = '{escape_value(object_value)}'")

    rel_pattern = f"[r:{normalize_predicate_type(predicate)}]" if predicate else "[r]"

    query = f"""
    MATCH (s:Entity)-{rel_pattern}->(o:Entity)
    WHERE {' AND '.join(where_clauses)}
    RETURN
        id(s) as subject_id,
        s.text as subject,
        type(r) as predicate,
        id(o) as object_id,
        o.text as object,
        id(r) as relation_id
    LIMIT {limit}
    """

    result = db.graph.query(query)

    triplets = []
    if result and hasattr(result, "result_set"):
        for row in result.result_set:
            triplets.append(
                {
                    "subject_id": str(row[0]),
                    "subject": ensure_text(row[1]),
                    "predicate": ensure_text(row[2]),
                    "object_id": str(row[3]),
                    "object": ensure_text(row[4]),
                    "relation_id": str(row[5]),
                }
            )

    return success_response(triplets=triplets)


@mcp_handler
def unlink_facts(
    db: FalkorDBClient,
    *,
    from_id: str,
    to_id: str,
    relation_type: Optional[str] = None,
    owner_id: str = "default",
) -> Dict:
    """Remove relations between facts."""
    owner_id = normalize_owner_id(owner_id)

    rel_pattern = (
        f"[r:{normalize_predicate_type(relation_type)}]" if relation_type else "[r]"
    )

    query = f"""
    MATCH (a)-{rel_pattern}->(b)
    WHERE id(a) = $from_id AND id(b) = $to_id
        AND a.owner_id = $owner_id AND b.owner_id = $owner_id
    DELETE r
    RETURN count(r) as deleted
    """

    result = execute_query(
        db,
        query,
        {
            "from_id": int(from_id),
            "to_id": int(to_id),
            "owner_id": owner_id,
        },
    )

    deleted = 0
    if result and hasattr(result, "result_set") and result.result_set:
        deleted = result.result_set[0][0]

    return success_response(deleted=deleted)
