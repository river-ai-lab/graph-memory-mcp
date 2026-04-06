import logging
import time
from typing import Any, Dict, List

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.utils import (
    escape_value,
    format_vecf32,
    normalize_owner_id,
    parse_embedding_value,
)
from graph_memory_mcp.jobs.lock import job_lock
from graph_memory_mcp.jobs.retry import retry_async

logger = logging.getLogger(__name__)

_DEDUP_CANDIDATE_LIMIT = 1000


def _parse_owner_ids(config: MCPServerConfig) -> List[str]:
    """Parse owner IDs from config."""
    raw = config.jobs_owner_ids or "default"
    owners = [o.strip() for o in raw.split(",") if o.strip()]
    return owners or ["default"]


def _resolve_owner_ids(db: FalkorDBClient, config: MCPServerConfig) -> List[str]:
    """Resolve owner IDs either from config or by discovering them from the graph."""
    if not config.jobs_process_all_owners:
        return _parse_owner_ids(config)

    query = """
    MATCH (n)
    WHERE n.owner_id IS NOT NULL AND n.owner_id <> ''
    RETURN DISTINCT n.owner_id as owner_id
    ORDER BY owner_id
    """

    try:
        result = db.graph.query(query)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Dedup job: failed to discover owners, falling back to jobs_owner_ids: %s",
            exc,
        )
        return _parse_owner_ids(config)

    if not result or not hasattr(result, "result_set") or not result.result_set:
        return _parse_owner_ids(config)

    owners = []
    for row in result.result_set:
        if not row or row[0] is None:
            continue
        raw_owner = row[0]
        if isinstance(raw_owner, bytes):
            raw_owner = raw_owner.decode("utf-8", errors="replace")
        owner_text = str(raw_owner).strip()
        if not owner_text:
            continue
        owners.append(normalize_owner_id(owner_text))

    resolved_owners = sorted(set(owners))
    return resolved_owners or _parse_owner_ids(config)


def _parse_candidate_rows(rows: List[List[Any]]) -> List[Dict[str, Any]]:
    """Convert raw query rows into candidate dictionaries."""
    candidates: List[Dict[str, Any]] = []
    for row in rows:
        embedding = parse_embedding_value(row[4])
        if not embedding:
            continue

        candidates.append(
            {
                "node_id": str(row[0]),
                "text": row[1],
                "created_at": row[2] or 0,
                "touched_at": row[3] or 0,
                "embedding": embedding,
            }
        )

    return candidates


def _query_candidate_batch(
    db: FalkorDBClient,
    *,
    label: str,
    owner_id: str,
    limit: int,
    touched_filter: str = "",
) -> List[Dict[str, Any]]:
    """Load one deterministic batch of pending dedup candidates."""
    if limit <= 0:
        return []

    query = f"""
    MATCH (n:{label})
    WHERE n.owner_id = '{escape_value(owner_id)}'
      AND (n.status IS NULL OR n.status = 'active')
      AND n.embedding IS NOT NULL
      AND (
        n.last_dedup_at IS NULL
        OR n.last_dedup_at < coalesce(n.updated_at, n.created_at)
      )
      {touched_filter}
    RETURN
      id(n) as node_id,
      n.text as text,
      n.created_at as created_at,
      coalesce(n.updated_at, n.created_at) as touched_at,
      n.embedding as embedding
    ORDER BY touched_at ASC, created_at ASC, node_id ASC
    LIMIT {limit}
    """

    result = db.graph.query(query)
    if not result or not hasattr(result, "result_set") or not result.result_set:
        return []

    return _parse_candidate_rows(result.result_set)


def _load_dedup_candidates(
    db: FalkorDBClient,
    *,
    label: str,
    owner_id: str,
    hours_threshold: int,
) -> List[Dict[str, Any]]:
    """Load pending same-owner nodes, prioritizing recent work and backfilling older backlog."""
    owner_id = normalize_owner_id(owner_id)
    time_threshold_ms = int((time.time() - hours_threshold * 3600) * 1000)

    recent_candidates = _query_candidate_batch(
        db,
        label=label,
        owner_id=owner_id,
        limit=_DEDUP_CANDIDATE_LIMIT,
        touched_filter=f"AND coalesce(n.updated_at, n.created_at) >= {time_threshold_ms}",
    )
    remaining = _DEDUP_CANDIDATE_LIMIT - len(recent_candidates)
    if remaining <= 0:
        return recent_candidates

    backlog_candidates = _query_candidate_batch(
        db,
        label=label,
        owner_id=owner_id,
        limit=remaining,
        touched_filter=f"AND coalesce(n.updated_at, n.created_at) < {time_threshold_ms}",
    )
    return recent_candidates + backlog_candidates


def _query_similar_nodes(
    db: FalkorDBClient,
    *,
    label: str,
    node_id: str,
    embedding: List[float],
    owner_id: str,
    threshold: float,
    top_k: int,
) -> List[Dict[str, Any]]:
    """Query same-owner similar nodes across the full active corpus."""
    max_distance = 1.0 - threshold
    query = f"""
    CALL db.idx.vector.queryNodes('{label}', 'embedding', {top_k + 1}, {format_vecf32(embedding)})
    YIELD node, score
    WHERE score <= {max_distance}
      AND node.owner_id = '{escape_value(owner_id)}'
      AND id(node) <> {int(node_id)}
      AND (node.status IS NULL OR node.status = 'active')
    RETURN
      id(node) as node_id,
      node.created_at as created_at,
      score
    ORDER BY score ASC, created_at ASC, node_id ASC
    LIMIT {top_k}
    """

    result = db.graph.query(query)
    if not result or not hasattr(result, "result_set") or not result.result_set:
        return []

    return [
        {
            "node_id": str(row[0]),
            "created_at": row[1] or 0,
            "score": float(row[2]),
        }
        for row in result.result_set
    ]


def _find_duplicate_groups(
    db: FalkorDBClient,
    *,
    label: str,
    threshold: float,
    max_group_size: int,
    owner_id: str,
    hours_threshold: int,
    candidates: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Find duplicate groups for one label using incremental candidates vs owner corpus."""
    owner_id = normalize_owner_id(owner_id)
    candidates = candidates or _load_dedup_candidates(
        db,
        label=label,
        owner_id=owner_id,
        hours_threshold=hours_threshold,
    )
    if not candidates:
        return []

    groups: List[Dict[str, Any]] = []
    top_k = max(max_group_size, getattr(db.config, "duplicate_top_k", 100))

    for candidate in candidates:
        matches = _query_similar_nodes(
            db,
            label=label,
            node_id=candidate["node_id"],
            embedding=candidate["embedding"],
            owner_id=owner_id,
            threshold=threshold,
            top_k=top_k,
        )
        if not matches:
            continue

        members = [
            {"node_id": candidate["node_id"], "created_at": candidate["created_at"]},
            *matches,
        ]

        deduped_members: dict[str, Dict[str, Any]] = {}
        for member in members:
            member_id = str(member["node_id"])
            created_at = member.get("created_at") or 0
            existing = deduped_members.get(member_id)
            if existing is None or created_at < (existing.get("created_at") or 0):
                deduped_members[member_id] = {
                    "node_id": member_id,
                    "created_at": created_at,
                }

        sorted_members = sorted(
            deduped_members.values(),
            key=lambda member: (member["created_at"], int(member["node_id"])),
        )
        if len(sorted_members) < 2:
            continue

        primary_id = sorted_members[0]["node_id"]
        duplicate_ids = [
            member["node_id"]
            for member in sorted_members[1 : max(2, max_group_size)]
            if member["node_id"] != primary_id
        ]
        if duplicate_ids:
            groups.append(
                {
                    "primary_id": primary_id,
                    "duplicate_ids": duplicate_ids,
                }
            )

    return groups


def _mark_nodes_deduped(
    db: FalkorDBClient,
    *,
    label: str,
    owner_id: str,
    node_ids: List[str],
) -> None:
    """Mark candidate nodes as checked so only new or updated nodes are reprocessed."""
    if not node_ids:
        return

    query = f"""
    MATCH (n:{label})
    WHERE id(n) IN $node_ids AND n.owner_id = $owner_id
    SET n.last_dedup_at = timestamp()
    RETURN count(n) as updated
    """
    db.graph.query(
        query,
        params={
            "node_ids": [int(node_id) for node_id in node_ids],
            "owner_id": normalize_owner_id(owner_id),
        },
    )


async def _find_duplicate_fact_groups(
    db: FalkorDBClient,
    threshold: float,
    max_group_size: int,
    owner_id: str,
    hours_threshold: int = 24,
    candidates: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Find duplicate fact groups across the same owner's active lifespan."""
    return _find_duplicate_groups(
        db,
        label="Fact",
        threshold=threshold,
        max_group_size=max_group_size,
        owner_id=owner_id,
        hours_threshold=hours_threshold,
        candidates=candidates,
    )


async def _merge_duplicate_facts(
    db: FalkorDBClient,
    fact_ids: List[str],
    owner_id: str,
) -> str | None:
    """Merge duplicate facts by redirecting relations and marking duplicates as outdated.

    Returns primary fact ID.
    """
    if not fact_ids or len(fact_ids) < 2:
        return None

    owner_id = normalize_owner_id(owner_id)
    primary_id = fact_ids[0]
    duplicate_ids = fact_ids[1:]

    for dup_id in duplicate_ids:
        try:
            get_out_rels_query = f"""
            MATCH (dup:Fact)-[r]->(target)
            WHERE id(dup) = {int(dup_id)}
              AND (dup.owner_id = '{owner_id}' OR dup.owner_id IS NULL)
            RETURN type(r) as rel_type, properties(r) as props, id(target) as target_id
            """
            out_rels = db.graph.query(get_out_rels_query)
            if out_rels and hasattr(out_rels, "result_set"):
                for row in out_rels.result_set:
                    rel_type, props, target_id = row
                    merge_query = f"""
                    MATCH (p:Fact), (t)
                    WHERE id(p) = {int(primary_id)} AND id(t) = {int(target_id)}
                    MERGE (p)-[new_r:{rel_type}]->(t)
                    SET new_r = $props
                    """
                    db.graph.query(merge_query, {"props": props})

            db.graph.query(
                f"MATCH (dup:Fact)-[r]->() WHERE id(dup) = {int(dup_id)} DELETE r"
            )
        except Exception as e:
            logger.warning(f"Failed to redirect outgoing relations for {dup_id}: {e}")

        try:
            get_in_rels_query = f"""
            MATCH (source)-[r]->(dup:Fact)
            WHERE id(dup) = {int(dup_id)}
              AND (dup.owner_id = '{owner_id}' OR dup.owner_id IS NULL)
            RETURN type(r) as rel_type, properties(r) as props, id(source) as source_id
            """
            in_rels = db.graph.query(get_in_rels_query)
            if in_rels and hasattr(in_rels, "result_set"):
                for row in in_rels.result_set:
                    rel_type, props, source_id = row
                    merge_query = f"""
                    MATCH (s), (p:Fact)
                    WHERE id(s) = {int(source_id)} AND id(p) = {int(primary_id)}
                    MERGE (s)-[new_r:{rel_type}]->(p)
                    SET new_r = $props
                    """
                    db.graph.query(merge_query, {"props": props})

            db.graph.query(
                f"MATCH ()-[r]->(dup:Fact) WHERE id(dup) = {int(dup_id)} DELETE r"
            )
        except Exception as e:
            logger.warning(f"Failed to redirect incoming relations for {dup_id}: {e}")

        mark_outdated_query = f"""
        MATCH (f:Fact)
        WHERE id(f) = {int(dup_id)}
          AND f.owner_id = '{owner_id}'
        SET f.status = 'outdated',
            f.metadata_str = coalesce(f.metadata_str, '{{}}')
        """

        try:
            db.graph.query(mark_outdated_query)
        except Exception as e:
            logger.warning(f"Failed to mark {dup_id} as outdated: {e}")

    update_primary_query = f"""
    MATCH (f:Fact)
    WHERE id(f) = {int(primary_id)}
      AND f.owner_id = '{owner_id}'
    SET f.last_dedup_at = timestamp()
    """

    try:
        db.graph.query(update_primary_query)
    except Exception as e:
        logger.warning(f"Failed to update last_dedup_at for primary {primary_id}: {e}")

    return primary_id


async def _find_duplicate_entity_groups(
    db: FalkorDBClient,
    threshold: float,
    max_group_size: int,
    owner_id: str,
    hours_threshold: int = 24,
    candidates: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Find duplicate entity groups across the same owner's active lifespan."""
    return _find_duplicate_groups(
        db,
        label="Entity",
        threshold=threshold,
        max_group_size=max_group_size,
        owner_id=owner_id,
        hours_threshold=hours_threshold,
        candidates=candidates,
    )


async def _merge_duplicate_entities(
    db: FalkorDBClient,
    entity_ids: List[str],
    owner_id: str,
) -> str | None:
    """Merge duplicate entities."""
    if not entity_ids or len(entity_ids) < 2:
        return None

    owner_id = normalize_owner_id(owner_id)
    primary_id = entity_ids[0]
    duplicate_ids = entity_ids[1:]

    for dup_id in duplicate_ids:
        try:
            get_out_rels_query = f"""
            MATCH (dup:Entity)-[r]->(target)
            WHERE id(dup) = {int(dup_id)}
              AND (dup.owner_id = '{owner_id}' OR dup.owner_id IS NULL)
            RETURN type(r) as rel_type, properties(r) as props, id(target) as target_id
            """
            out_rels = db.graph.query(get_out_rels_query)
            if out_rels and hasattr(out_rels, "result_set"):
                for row in out_rels.result_set:
                    rel_type, props, target_id = row
                    merge_query = f"""
                    MATCH (p:Entity), (t)
                    WHERE id(p) = {int(primary_id)} AND id(t) = {int(target_id)}
                    MERGE (p)-[new_r:{rel_type}]->(t)
                    SET new_r = $props
                    """
                    db.graph.query(merge_query, {"props": props})

            db.graph.query(
                f"MATCH (dup:Entity)-[r]->() WHERE id(dup) = {int(dup_id)} DELETE r"
            )
        except Exception as e:
            logger.warning(
                f"Failed to redirect outgoing relations for entity {dup_id}: {e}"
            )

        try:
            get_in_rels_query = f"""
            MATCH (source)-[r]->(dup:Entity)
            WHERE id(dup) = {int(dup_id)}
              AND (dup.owner_id = '{owner_id}' OR dup.owner_id IS NULL)
            RETURN type(r) as rel_type, properties(r) as props, id(source) as source_id
            """
            in_rels = db.graph.query(get_in_rels_query)
            if in_rels and hasattr(in_rels, "result_set"):
                for row in in_rels.result_set:
                    rel_type, props, source_id = row
                    merge_query = f"""
                    MATCH (s), (p:Entity)
                    WHERE id(s) = {int(source_id)} AND id(p) = {int(primary_id)}
                    MERGE (s)-[new_r:{rel_type}]->(p)
                    SET new_r = $props
                    """
                    db.graph.query(merge_query, {"props": props})

            db.graph.query(
                f"MATCH ()-[r]->(dup:Entity) WHERE id(dup) = {int(dup_id)} DELETE r"
            )
        except Exception as e:
            logger.warning(
                f"Failed to redirect incoming relations for entity {dup_id}: {e}"
            )

        mark_outdated_query = f"""
        MATCH (e:Entity)
        WHERE id(e) = {int(dup_id)}
          AND e.owner_id = '{owner_id}'
        SET e.status = 'outdated'
        """

        try:
            db.graph.query(mark_outdated_query)
        except Exception as e:
            logger.warning(f"Failed to mark entity {dup_id} as outdated: {e}")

    update_primary_query = f"""
    MATCH (e:Entity)
    WHERE id(e) = {int(primary_id)}
      AND e.owner_id = '{owner_id}'
    SET e.last_dedup_at = timestamp()
    """

    try:
        db.graph.query(update_primary_query)
    except Exception as e:
        logger.warning(f"Failed to update last_dedup_at for entity {primary_id}: {e}")

    return primary_id


async def deduplicate_facts(db: FalkorDBClient, config: MCPServerConfig) -> None:
    """Background job: periodic same-owner deduplication for facts and entities."""
    if not config.enabled:
        logger.info("Dedup job: memory server is disabled in config, skipping")
        return

    if not config.jobs_enabled or not config.job_deduplicate_enabled:
        logger.info("Dedup job: disabled, skipping")
        return

    retry_max_attempts = config.job_retry_max_attempts
    retry_backoff_base = config.job_retry_backoff_base
    retry_backoff_max = config.job_retry_backoff_max

    find_duplicates_with_retry = retry_async(
        max_attempts=retry_max_attempts,
        backoff_base=retry_backoff_base,
        backoff_max=retry_backoff_max,
    )(_find_duplicate_fact_groups)

    merge_duplicates_with_retry = retry_async(
        max_attempts=retry_max_attempts,
        backoff_base=retry_backoff_base,
        backoff_max=retry_backoff_max,
    )(_merge_duplicate_facts)

    find_entity_duplicates_with_retry = retry_async(
        max_attempts=retry_max_attempts,
        backoff_base=retry_backoff_base,
        backoff_max=retry_backoff_max,
    )(_find_duplicate_entity_groups)

    merge_entity_duplicates_with_retry = retry_async(
        max_attempts=retry_max_attempts,
        backoff_base=retry_backoff_base,
        backoff_max=retry_backoff_max,
    )(_merge_duplicate_entities)

    try:
        db.create_vector_index()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dedup job: failed to ensure Fact vector index: %s", exc)

    try:
        db.create_entity_vector_index()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dedup job: failed to ensure Entity vector index: %s", exc)

    threshold = config.job_deduplicate_similarity_threshold
    max_group_size = max(2, config.duplicate_max_group_size)
    hours_threshold = config.job_deduplicate_hours_threshold

    lock_ttl = config.jobs_lock_ttl_seconds
    owners = _resolve_owner_ids(db, config)

    for owner_id in owners:
        lock_key = f"graph_memory_mcp:job:deduplicate_facts:{owner_id}"

        if not hasattr(db, "redis_client") or db.redis_client is None:
            logger.warning("Dedup job: Redis not available, running without lock")
            acquired = True
            lock_context = None
        else:
            lock_context = job_lock(db.redis_client, lock_key, ttl_seconds=lock_ttl)
            acquired = lock_context.__enter__()

        try:
            if not acquired:
                logger.info("Dedup job: lock busy for owner_id=%s, skipping", owner_id)
                continue

            logger.info(
                "Dedup job: scanning owner_id=%s (threshold=%.3f, max_group_size=%s, hours_threshold=%s)",
                owner_id,
                threshold,
                max_group_size,
                hours_threshold,
            )

            fact_candidates = _load_dedup_candidates(
                db,
                label="Fact",
                owner_id=owner_id,
                hours_threshold=hours_threshold,
            )
            start_time = time.time()
            try:
                fact_groups = (
                    await find_duplicates_with_retry(
                        db,
                        threshold,
                        max_group_size,
                        owner_id=owner_id,
                        hours_threshold=hours_threshold,
                        candidates=fact_candidates,
                    )
                    if fact_candidates
                    else []
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Dedup job: failed to find duplicate fact groups (owner_id=%s): %s",
                    owner_id,
                    exc,
                )
                continue

            if not fact_groups:
                logger.info(
                    "Dedup job: no duplicate fact groups found (owner_id=%s, candidates=%d)",
                    owner_id,
                    len(fact_candidates),
                )
            else:
                logger.info(
                    "Dedup job: found %d duplicate fact groups (owner_id=%s, candidates=%d)",
                    len(fact_groups),
                    owner_id,
                    len(fact_candidates),
                )

                merged_groups = 0
                merged_facts = 0
                failed_groups = 0
                seen_ids: set[str] = set()

                for group in fact_groups:
                    primary_id = group.get("primary_id")
                    duplicate_ids = group.get("duplicate_ids") or []

                    if not primary_id or not duplicate_ids or primary_id in seen_ids:
                        continue

                    filtered_dupes = [
                        dup_id
                        for dup_id in duplicate_ids
                        if dup_id not in seen_ids and dup_id != primary_id
                    ]
                    if not filtered_dupes:
                        continue

                    fact_ids = [primary_id, *filtered_dupes]
                    try:
                        result_id = await merge_duplicates_with_retry(
                            db,
                            fact_ids,
                            owner_id=owner_id,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Dedup job: failed to merge fact group for primary %s: %s",
                            primary_id,
                            exc,
                        )
                        failed_groups += 1
                        continue

                    if result_id:
                        merged_groups += 1
                        merged_facts += len(filtered_dupes)
                        seen_ids.add(primary_id)
                        seen_ids.update(filtered_dupes)
                    else:
                        failed_groups += 1

                logger.info(
                    "Dedup job (facts) finished (owner_id=%s): merged_groups=%d, merged_facts=%d, failed_groups=%d, elapsed_time=%.2fs",
                    owner_id,
                    merged_groups,
                    merged_facts,
                    failed_groups,
                    time.time() - start_time,
                )

            try:
                _mark_nodes_deduped(
                    db,
                    label="Fact",
                    owner_id=owner_id,
                    node_ids=[candidate["node_id"] for candidate in fact_candidates],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Dedup job: failed to mark fact candidates as deduped (owner_id=%s): %s",
                    owner_id,
                    exc,
                )

            entity_candidates = _load_dedup_candidates(
                db,
                label="Entity",
                owner_id=owner_id,
                hours_threshold=hours_threshold,
            )
            try:
                entity_groups = (
                    await find_entity_duplicates_with_retry(
                        db,
                        threshold,
                        max_group_size,
                        owner_id=owner_id,
                        hours_threshold=hours_threshold,
                        candidates=entity_candidates,
                    )
                    if entity_candidates
                    else []
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Dedup job: failed to find duplicate entity groups (owner_id=%s): %s",
                    owner_id,
                    exc,
                )
                continue

            if not entity_groups:
                logger.info(
                    "Dedup job: no duplicate entity groups found (owner_id=%s, candidates=%d)",
                    owner_id,
                    len(entity_candidates),
                )
            else:
                merged_entity_groups = 0
                failed_entity_groups = 0
                seen_entity_ids: set[str] = set()

                for group in entity_groups:
                    primary_id = group.get("primary_id")
                    duplicate_ids = group.get("duplicate_ids") or []
                    if (
                        not primary_id
                        or not duplicate_ids
                        or primary_id in seen_entity_ids
                    ):
                        continue

                    filtered_dupes = [
                        dup_id
                        for dup_id in duplicate_ids
                        if dup_id not in seen_entity_ids and dup_id != primary_id
                    ]
                    if not filtered_dupes:
                        continue

                    entity_ids = [primary_id, *filtered_dupes]
                    try:
                        result_id = await merge_entity_duplicates_with_retry(
                            db,
                            entity_ids=entity_ids,
                            owner_id=owner_id,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Dedup job: failed to merge entity group for primary %s: %s",
                            primary_id,
                            exc,
                        )
                        failed_entity_groups += 1
                        continue

                    if result_id:
                        merged_entity_groups += 1
                        seen_entity_ids.add(primary_id)
                        seen_entity_ids.update(filtered_dupes)
                    else:
                        failed_entity_groups += 1

                logger.info(
                    "Dedup job (entities) finished (owner_id=%s): merged_groups=%d, failed_groups=%d",
                    owner_id,
                    merged_entity_groups,
                    failed_entity_groups,
                )

            try:
                _mark_nodes_deduped(
                    db,
                    label="Entity",
                    owner_id=owner_id,
                    node_ids=[candidate["node_id"] for candidate in entity_candidates],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Dedup job: failed to mark entity candidates as deduped (owner_id=%s): %s",
                    owner_id,
                    exc,
                )

        finally:
            if lock_context is not None:
                lock_context.__exit__(None, None, None)
