"""Admin handlers for MCP Graph Memory (stats, health, summary)."""

import logging
import time
from typing import Any, Dict, Optional

from graph_memory_mcp.graph_memory import mcp_handlers_nodes
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.utils import (
    ensure_text,
    error_response,
    mcp_handler,
    normalize_owner_id,
    normalize_predicate_type,
    parse_embedding_value,
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
        # Graph-per-owner: check indexes across existing owner graphs (capped).
        owners = db.list_owners()[:20] if hasattr(db, "list_owners") else []
        if owners:
            vector_ok = all(
                all(db.get_vector_index_status(owner_id=o).values()) for o in owners
            )
        else:
            vector_ok = True  # no owner graphs yet — nothing to index
    except Exception as exc:
        logger.error("health_check: vector index probe failed: %s", exc)

    return success_response(
        falkordb=falkordb_ok,
        embeddings=embeddings_ok,
        vector_index=vector_ok,
        healthy=falkordb_ok and embeddings_ok and vector_ok,
        cache=db.cache.stats(),
    )


@mcp_handler
def get_stats(db: FalkorDBClient, *, owner_id: str = "default") -> Dict:
    """Get graph statistics."""
    owner_id = normalize_owner_id(owner_id)
    params = {"owner_id": owner_id}

    # Count only public memory labels (exclude FactVersion, Collection, etc.)
    query = """
    MATCH (n)
    WHERE n.owner_id = $owner_id AND (n:Fact OR n:Entity)
    WITH labels(n)[0] as label, count(n) as count
    RETURN label, count
    """

    result = db.query(query, params=params)

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
    status_query = """
    MATCH (f:Fact)
    WHERE f.owner_id = $owner_id
    WITH f.status as status, count(f) as count
    RETURN status, count
    """

    result = db.query(status_query, params=params)
    if result and hasattr(result, "result_set"):
        for row in result.result_set:
            status = row[0]
            count = row[1]
            if status == "active":
                stats["active_facts"] = count
            elif status == "outdated":
                stats["outdated_facts"] = count

    # Get relation count
    rel_query = """
    MATCH (a)-[r]->(b)
    WHERE a.owner_id = $owner_id
      AND b.owner_id = $owner_id
    RETURN count(r) as total_relations
    """

    result = db.query(rel_query, params=params)
    if result and hasattr(result, "result_set") and result.result_set:
        stats["total_relations"] = result.result_set[0][0]
    else:
        stats["total_relations"] = 0

    return success_response(stats=stats)


@mcp_handler
def get_brief(
    db: FalkorDBClient,
    *,
    owner_id: str = "default",
    limit: int = 10,
) -> Dict:
    """Session warm-up: top facts (by connectivity/recency), contradictions, stats."""
    owner_id = normalize_owner_id(owner_id)
    limit = max(1, min(int(limit), 50))
    params = {"owner_id": owner_id}

    top_query = f"""
    MATCH (f:Fact)
    WHERE f.owner_id = $owner_id
      AND (f.status IS NULL OR f.status = 'active')
    OPTIONAL MATCH (f)-[r]-()
    WITH f, count(r) as degree
    ORDER BY degree DESC, f.created_at DESC
    LIMIT {limit}
    RETURN f.uid as node_id, f.text as text, degree, f.created_at as created_at
    """
    top_facts = []
    result = db.query(top_query, params=params)
    if result and hasattr(result, "result_set"):
        for row in result.result_set:
            top_facts.append(
                {
                    "node_id": str(row[0]),
                    "text": ensure_text(row[1]),
                    "degree": row[2],
                    "created_at": row[3],
                }
            )

    contradictions_query = """
    MATCH (a)-[r:CONTRADICTS]-(b)
    WHERE a.owner_id = $owner_id AND b.owner_id = $owner_id
      AND a.uid < b.uid
    RETURN a.uid, a.text, b.uid, b.text
    LIMIT 10
    """
    contradictions = []
    result = db.query(contradictions_query, params=params)
    if result and hasattr(result, "result_set"):
        for row in result.result_set:
            contradictions.append(
                {
                    "from_id": str(row[0]),
                    "from_text": ensure_text(row[1]),
                    "to_id": str(row[2]),
                    "to_text": ensure_text(row[3]),
                }
            )

    stale_days = getattr(getattr(db, "config", None), "stale_facts_days", 30)
    stale_cutoff_ms = int(time.time() * 1000) - stale_days * 24 * 3600 * 1000
    stale_query = """
    MATCH (f:Fact)
    WHERE f.owner_id = $owner_id
      AND (f.status IS NULL OR f.status = 'active')
      AND coalesce(f.last_accessed_at, f.created_at) < $cutoff_ms
    RETURN f.uid, f.text, f.last_accessed_at, f.access_count
    ORDER BY coalesce(f.last_accessed_at, f.created_at) ASC
    LIMIT 10
    """
    stale_facts = []
    result = db.query(
        stale_query, params={"owner_id": owner_id, "cutoff_ms": stale_cutoff_ms}
    )
    if result and hasattr(result, "result_set"):
        for row in result.result_set:
            stale_facts.append(
                {
                    "node_id": str(row[0]),
                    "text": ensure_text(row[1]),
                    "last_accessed_at": row[2],
                    "access_count": row[3] or 0,
                }
            )

    stats_result = get_stats(db, owner_id=owner_id)

    return success_response(
        top_facts=top_facts,
        contradictions=contradictions,
        stale_facts=stale_facts,
        stats=stats_result.get("stats", {}),
    )


_EXPORT_LABELS = ("Fact", "Entity")


@mcp_handler
def export_owner(
    db: FalkorDBClient,
    *,
    owner_id: str = "default",
    include_embeddings: bool = True,
    include_versions: bool = False,
    offset: int = 0,
    limit: Optional[int] = None,
    section: str = "all",
) -> Dict:
    """Export owner data (nodes + relations) as JSON-serializable payload.

    One JSON object per node/relation — write each list item as a line for JSONL.

    Pagination for large owners: pass `limit` (+ `offset`) and page one
    `section` at a time ("nodes", then "relations"); the response carries
    `has_more` / `next_offset`. Default (`section="all"`, no limit) exports
    everything in one response.
    """
    owner_id = normalize_owner_id(owner_id)
    if section not in ("all", "nodes", "relations"):
        return error_response(
            "section must be one of: all, nodes, relations",
            code="memory_validation_error",
        )
    if section == "all" and (offset or limit is not None):
        section = "nodes"
    offset = max(0, int(offset))
    page_clause = ""
    if limit is not None:
        page_clause = f" SKIP {offset} LIMIT {int(limit)}"

    nodes = []
    if section in ("all", "nodes"):
        result = db.query(
            f"""
            MATCH (n)
            WHERE n.owner_id = $owner_id AND (n:Fact OR n:Entity OR n:FactVersion)
            RETURN labels(n)[0], properties(n)
            ORDER BY n.uid{page_clause}
            """,
            params={"owner_id": owner_id},
        )
        for row in getattr(result, "result_set", None) or []:
            label = str(row[0])
            if label == "FactVersion" and not include_versions:
                continue
            props = dict(row[1] or {})
            embedding = props.pop("embedding", None)
            if include_embeddings and embedding is not None:
                props["embedding"] = parse_embedding_value(embedding)
            nodes.append({"label": label, "properties": props})

    relations = []
    if section in ("all", "relations"):
        result = db.query(
            f"""
            MATCH (a)-[r]->(b)
            WHERE a.owner_id = $owner_id AND b.owner_id = $owner_id
            RETURN a.uid, type(r), b.uid, properties(r)
            ORDER BY a.uid, b.uid{page_clause}
            """,
            params={"owner_id": owner_id},
        )
        for row in getattr(result, "result_set", None) or []:
            relations.append(
                {
                    "from_id": str(row[0]),
                    "relation_type": str(row[1]),
                    "to_id": str(row[2]),
                    "properties": dict(row[3] or {}),
                }
            )

    response = success_response(
        owner_id=owner_id,
        nodes=nodes,
        relations=relations,
        node_count=len(nodes),
        relation_count=len(relations),
    )
    if limit is not None:
        page_size = len(nodes) if section == "nodes" else len(relations)
        response["section"] = section
        response["offset"] = offset
        response["has_more"] = page_size >= int(limit)
        response["next_offset"] = offset + page_size
    return response


_IMPORT_BATCH_SIZE = 200


@mcp_handler
def import_owner(
    db: FalkorDBClient,
    *,
    owner_id: str,
    nodes: list,
    relations: Optional[list] = None,
    regenerate_embeddings: bool = False,
) -> Dict:
    """Import a previously exported payload into `owner_id`.

    Nodes are merged by `uid` (idempotent) in UNWIND batches grouped by label;
    relations in batches grouped by type. Embeddings come from the payload, or
    are recomputed when regenerate_embeddings=true (or missing).
    """
    owner_id = normalize_owner_id(owner_id)

    imported = 0
    skipped = 0

    # Group nodes by (label, has_embedding) for batched UNWIND merges.
    rows_by_group: Dict[tuple, list] = {}
    for node in nodes or []:
        label = str((node or {}).get("label") or "")
        props = dict((node or {}).get("properties") or {})
        uid = ensure_text(props.get("uid"))
        text = ensure_text(props.get("text"))
        if label not in _EXPORT_LABELS or not uid:
            skipped += 1
            continue
        embedding = props.pop("embedding", None)
        if (regenerate_embeddings or not embedding) and text:
            embedding = db.get_embedding(text)
        props["owner_id"] = owner_id
        row = {"uid": uid, "props": props}
        if embedding:
            row["emb"] = [float(v) for v in embedding]
        rows_by_group.setdefault((label, bool(embedding)), []).append(row)

    for (label, has_emb), rows in rows_by_group.items():
        emb_clause = ", n.embedding = vecf32(row.emb)" if has_emb else ""
        for start in range(0, len(rows), _IMPORT_BATCH_SIZE):
            batch = rows[start : start + _IMPORT_BATCH_SIZE]
            db.query(
                f"""
                UNWIND $rows AS row
                MERGE (n:{label} {{uid: row.uid}})
                SET n = row.props{emb_clause}
                """,
                params={"rows": batch, "owner_id": owner_id},
            )
            imported += len(batch)

    # Group relations by type for batched UNWIND merges.
    imported_relations = 0
    rels_by_type: Dict[str, list] = {}
    for rel in relations or []:
        rel_type = normalize_predicate_type(str((rel or {}).get("relation_type") or ""))
        from_id = ensure_text((rel or {}).get("from_id"))
        to_id = ensure_text((rel or {}).get("to_id"))
        if not (from_id and to_id and rel_type):
            skipped += 1
            continue
        rels_by_type.setdefault(rel_type, []).append(
            {
                "from_id": from_id,
                "to_id": to_id,
                "props": dict((rel or {}).get("properties") or {}),
            }
        )

    for rel_type, rows in rels_by_type.items():
        for start in range(0, len(rows), _IMPORT_BATCH_SIZE):
            batch = rows[start : start + _IMPORT_BATCH_SIZE]
            db.query(
                f"""
                UNWIND $rows AS row
                MATCH (a), (b)
                WHERE a.uid = row.from_id AND b.uid = row.to_id
                  AND a.owner_id = $owner_id AND b.owner_id = $owner_id
                MERGE (a)-[r:{rel_type}]->(b)
                SET r = row.props
                """,
                params={"rows": batch, "owner_id": owner_id},
            )
            imported_relations += len(batch)

    db.cache.invalidate_search()
    return success_response(
        owner_id=owner_id,
        imported_nodes=imported,
        imported_relations=imported_relations,
        skipped=skipped,
    )


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
                config=config,
            )
        except Exception as link_exc:
            logger.warning("Failed to link summary to fact %s: %s", fact_id, link_exc)

    return success_response(summary=summary_node)
