"""Relation and triplet handlers for MCP Graph Memory."""

import logging
import re
from typing import Any, Dict, Optional

from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.relation_policy import evaluate_relation_policy
from graph_memory_mcp.graph_memory.utils import (
    dump_json,
    ensure_text,
    error_response,
    mcp_handler,
    new_uid,
    normalize_entity_name,
    normalize_owner_id,
    normalize_predicate_type,
    require_node_id,
    success_response,
    validate_inputs,
)

logger = logging.getLogger(__name__)

_PROPERTY_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_property_keys(properties: Optional[Dict]) -> Optional[str]:
    """Property keys are interpolated into Cypher; restrict to identifiers."""
    for key in properties or {}:
        if not _PROPERTY_KEY_RE.match(str(key)):
            return f"Invalid property key: {key!r} (use letters, digits, _)"
    return None


@mcp_handler
def create_relation(
    db: FalkorDBClient,
    *,
    from_id: str,
    to_id: str,
    relation_type: str,
    properties: Optional[Dict] = None,
    owner_id: str = "default",
    config: Any = None,
) -> Dict:
    """Create a relation between two nodes."""
    owner_id = normalize_owner_id(owner_id)
    from_id = require_node_id(from_id, "from_id")
    to_id = require_node_id(to_id, "to_id")
    if error := validate_inputs(locals(), config):
        return error_response(error, code="memory_validation_error")
    if error := _validate_property_keys(properties):
        return error_response(error, code="memory_validation_error")

    rel_type = normalize_predicate_type(relation_type)
    proceed, warning, policy_error = evaluate_relation_policy(config, rel_type)
    if not proceed:
        return error_response(policy_error, code="memory_relation_policy_error")

    props_str = ""
    if properties:
        props_str = ", " + ", ".join(f"r.{k} = ${k}" for k in properties.keys())

    params = {
        "from_id": from_id,
        "to_id": to_id,
        "owner_id": owner_id,
    }
    if properties:
        params.update(properties)

    rows = db.merge_relation(
        rel_type=rel_type, params=params, prop_assignments=props_str
    )
    if not rows:
        return error_response("Failed to create relation", code="memory_service_error")

    db.cache.invalidate_search()

    response = success_response(relation_type=rel_type)
    if warning:
        response["warning"] = warning
    return response


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
    config: Any = None,
) -> Dict:
    """Create a subject-predicate-object triplet."""
    owner_id = normalize_owner_id(owner_id)

    rel_type = normalize_predicate_type(predicate)
    proceed, warning, policy_error = evaluate_relation_policy(config, rel_type)
    if not proceed:
        return error_response(policy_error, code="memory_relation_policy_error")

    # Create or get subject entity
    subj_emb = db.get_embedding(subject)
    obj_emb = db.get_embedding(object_value)

    subj_emb_expr = db.embedding_literal("subj_emb", bool(subj_emb))
    obj_emb_expr = db.embedding_literal("obj_emb", bool(obj_emb))
    # Lazy import: nodes ↔ relations would otherwise cycle at module load.
    from graph_memory_mcp.graph_memory.mcp_handlers_nodes import metadata_promoted_props

    try:
        promoted = metadata_promoted_props(metadata)
    except ValueError as exc:
        return error_response(str(exc), code="memory_validation_error")
    metadata_str = dump_json(metadata or {})
    params = {
        "subject": subject,
        "object": object_value,
        "subject_norm": normalize_entity_name(subject),
        "object_norm": normalize_entity_name(object_value),
        "owner_id": owner_id,
        "subj_uid": new_uid(),
        "obj_uid": new_uid(),
        "metadata_str": metadata_str,
        **promoted,
    }
    if subj_emb:
        params["subj_emb"] = subj_emb
    if obj_emb:
        params["obj_emb"] = obj_emb

    rows = db.merge_triplet(
        rel_type=rel_type,
        params=params,
        subj_emb_expr=subj_emb_expr,
        obj_emb_expr=obj_emb_expr,
    )
    if not rows:
        return error_response("Failed to create triplet", code="memory_service_error")

    row = rows[0]
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
        proceed_x, warning_x, err_x = evaluate_relation_policy(
            config, "EXTRACTED_FROM", internal=True
        )
        if not proceed_x:
            response = success_response(triplet=triplet)
            response["link_errors"] = [
                {"relation_type": "EXTRACTED_FROM", "error": err_x}
            ]
            if warning:
                response["warning"] = warning
            db.cache.invalidate_search()
            return response
        if warning_x and warning:
            warning = f"{warning}; {warning_x}"
        elif warning_x:
            warning = warning_x

        db.link_extracted_from(
            fact_id=require_node_id(fact_id, "fact_id"),
            subject_id=str(row[0]),
            owner_id=owner_id,
        )

    db.cache.invalidate_search()

    response = success_response(triplet=triplet)
    if warning:
        response["warning"] = warning
    return response


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
    max_limit = getattr(getattr(db, "config", None), "max_search_limit", 100)
    limit = max(1, min(int(limit), max_limit))

    where_clauses = ["s.owner_id = $owner_id"]
    params: Dict[str, Any] = {"owner_id": owner_id}

    if subject:
        where_clauses.append("s.name_norm = $subject_norm")
        params["subject_norm"] = normalize_entity_name(subject)
    if object_value:
        where_clauses.append("o.name_norm = $object_norm")
        params["object_norm"] = normalize_entity_name(object_value)

    rel_pattern = f"[r:{normalize_predicate_type(predicate)}]" if predicate else "[r]"

    triplets = []
    for row in db.search_triplet_rows(
        rel_pattern=rel_pattern,
        where_sql=" AND ".join(where_clauses),
        params=params,
        limit=limit,
    ):
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
    from_id = require_node_id(from_id, "from_id")
    to_id = require_node_id(to_id, "to_id")

    rel_pattern = (
        f"[r:{normalize_predicate_type(relation_type)}]" if relation_type else "[r]"
    )

    rows = db.unlink_relation(
        rel_pattern=rel_pattern,
        params={"from_id": from_id, "to_id": to_id, "owner_id": owner_id},
    )
    deleted = rows[0][0] if rows else 0

    return success_response(deleted=deleted)
