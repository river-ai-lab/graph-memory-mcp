import logging
import time
from typing import Any, Dict, List

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.utils import format_vecf32, normalize_owner_id
from graph_memory_mcp.jobs.lock import job_lock
from graph_memory_mcp.jobs.retry import retry_async

logger = logging.getLogger(__name__)


def _parse_owner_ids(config: MCPServerConfig) -> List[str]:
    """Parse owner IDs from config."""
    raw = config.jobs_owner_ids or "default"
    owners = [o.strip() for o in raw.split(",") if o.strip()]
    return owners or ["default"]


async def _find_duplicate_fact_groups(
    db: FalkorDBClient,
    threshold: float,
    max_group_size: int,
    owner_id: str,
    hours_threshold: int = 24,
) -> List[Dict[str, Any]]:
    """Find duplicate fact groups using vector similarity.

    Returns list of groups: [{"primary_id": "123", "duplicate_ids": ["456", "789"]}, ...]
    """
    owner_id = normalize_owner_id(owner_id)

    # Calculate time threshold (only check recent facts for incremental dedup)
    time_threshold_ms = int((time.time() - hours_threshold * 3600) * 1000)

    # Find facts created within time window
    query = f"""
    MATCH (f:Fact)
    WHERE f.owner_id = '{owner_id}'
      AND f.created_at >= {time_threshold_ms}
      AND (f.status IS NULL OR f.status = 'active')
      AND (f.last_dedup_at IS NULL OR f.last_dedup_at < {time_threshold_ms})
    RETURN id(f) as fact_id, f.embedding as embedding
    LIMIT 1000
    """

    result = db.graph.query(query)
    if not result or not hasattr(result, "result_set") or not result.result_set:
        return []

    # For each fact, find similar facts
    groups = []
    max_distance = 1.0 - threshold

    for row in result.result_set:
        fact_id = str(row[0])
        embedding = row[1]

        # Skip if no embedding
        if not embedding:
            continue

        # Convert embedding to vecf32 format
        if isinstance(embedding, (list, tuple)):
            embedding_vec = format_vecf32(list(embedding))
        else:
            # Already in vecf32 format or need parsing
            continue

        # Find similar facts
        similar_query = f"""
        CALL db.idx.vector.queryNodes('Fact', 'embedding', 10, {embedding_vec})
        YIELD node, score
        WHERE score <= {max_distance}
          AND node.owner_id = '{owner_id}'
          AND id(node) <> {int(fact_id)}
          AND (node.status IS NULL OR node.status = 'active')
        RETURN id(node) as similar_id, score
        ORDER BY score ASC
        LIMIT {max_group_size - 1}
        """

        similar_result = db.graph.query(similar_query)
        if (
            not similar_result
            or not hasattr(similar_result, "result_set")
            or not similar_result.result_set
        ):
            continue

        duplicate_ids = [str(r[0]) for r in similar_result.result_set]

        if duplicate_ids:
            groups.append(
                {
                    "primary_id": fact_id,
                    "duplicate_ids": duplicate_ids,
                }
            )

    return groups


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

    # Primary is the first one (oldest)
    primary_id = fact_ids[0]
    duplicate_ids = fact_ids[1:]

    # For each duplicate, redirect its relations to primary and mark as outdated
    for dup_id in duplicate_ids:
        # 1) Redirect outgoing relations
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

            # Delete old outgoing relations
            db.graph.query(
                f"MATCH (dup:Fact)-[r]->() WHERE id(dup) = {int(dup_id)} DELETE r"
            )
        except Exception as e:
            logger.warning(f"Failed to redirect outgoing relations for {dup_id}: {e}")

        # 2) Redirect incoming relations
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

            # Delete old incoming relations
            db.graph.query(
                f"MATCH ()-[r]->(dup:Fact) WHERE id(dup) = {int(dup_id)} DELETE r"
            )
        except Exception as e:
            logger.warning(f"Failed to redirect incoming relations for {dup_id}: {e}")

        # Mark duplicate as outdated
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

    # Update primary's last_dedup_at
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
) -> List[Dict[str, Any]]:
    """Find duplicate entity groups using vector similarity."""
    owner_id = normalize_owner_id(owner_id)

    time_threshold_ms = int((time.time() - hours_threshold * 3600) * 1000)

    query = f"""
    MATCH (e:Entity)
    WHERE e.owner_id = '{owner_id}'
      AND e.created_at >= {time_threshold_ms}
      AND (e.status IS NULL OR e.status = 'active')
      AND (e.last_dedup_at IS NULL OR e.last_dedup_at < {time_threshold_ms})
    RETURN id(e) as entity_id, e.embedding as embedding
    LIMIT 1000
    """

    result = db.graph.query(query)
    if not result or not hasattr(result, "result_set") or not result.result_set:
        return []

    groups = []
    max_distance = 1.0 - threshold

    for row in result.result_set:
        entity_id = str(row[0])
        embedding = row[1]

        if not embedding:
            continue

        if isinstance(embedding, (list, tuple)):
            embedding_vec = format_vecf32(list(embedding))
        else:
            continue

        similar_query = f"""
        CALL db.idx.vector.queryNodes('Entity', 'embedding', 10, {embedding_vec})
        YIELD node, score
        WHERE score <= {max_distance}
          AND node.owner_id = '{owner_id}'
          AND id(node) <> {int(entity_id)}
          AND (node.status IS NULL OR node.status = 'active')
        RETURN id(node) as similar_id, score
        ORDER BY score ASC
        LIMIT {max_group_size - 1}
        """

        similar_result = db.graph.query(similar_query)
        if (
            not similar_result
            or not hasattr(similar_result, "result_set")
            or not similar_result.result_set
        ):
            continue

        duplicate_ids = [str(r[0]) for r in similar_result.result_set]

        if duplicate_ids:
            groups.append(
                {
                    "primary_id": entity_id,
                    "duplicate_ids": duplicate_ids,
                }
            )

    return groups


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
        # 1) Redirect outgoing relations
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

            # Delete old outgoing relations
            db.graph.query(
                f"MATCH (dup:Entity)-[r]->() WHERE id(dup) = {int(dup_id)} DELETE r"
            )
        except Exception as e:
            logger.warning(
                f"Failed to redirect outgoing relations for entity {dup_id}: {e}"
            )

        # 2) Redirect incoming relations
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

            # Delete old incoming relations
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
    """
    Background job: periodic search and merge of duplicate facts.
    """
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

    # Ensure vector indices exist
    try:
        db.create_vector_index()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dedup job: failed to ensure Fact vector index: %s", exc)

    try:
        db.create_entity_vector_index()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dedup job: failed to ensure Entity vector index: %s", exc)

    threshold = config.job_deduplicate_similarity_threshold
    max_group_size = 2  # Pairwise deduplication
    hours_threshold = config.job_deduplicate_hours_threshold

    lock_ttl = config.jobs_lock_ttl_seconds
    owners = _parse_owner_ids(config)

    for owner_id in owners:
        lock_key = f"graph_memory_mcp:job:deduplicate_facts:{owner_id}"

        # Handle Redis lock availability
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
                "Dedup job: searching for duplicate fact groups "
                "(threshold=%.3f, max_group_size=%s, hours_threshold=%s, owner_id=%s)",
                threshold,
                max_group_size,
                hours_threshold,
                owner_id,
            )

            start_time = time.time()
            try:
                groups = await find_duplicates_with_retry(
                    db,
                    threshold,
                    max_group_size,
                    owner_id=owner_id,
                    hours_threshold=hours_threshold,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Dedup job: failed to find duplicate fact groups (owner_id=%s): %s",
                    owner_id,
                    exc,
                )
                continue

            if not groups:
                logger.info(
                    "Dedup job: no duplicate fact groups found (owner_id=%s)", owner_id
                )
            else:
                logger.info(
                    "Dedup job: found %d duplicate groups (owner_id=%s)",
                    len(groups),
                    owner_id,
                )

                merged_groups = 0
                merged_facts = 0
                failed_groups = 0
                seen_ids = set()

                for group in groups:
                    primary_id = group.get("primary_id")
                    duplicate_ids = group.get("duplicate_ids") or []

                    if not primary_id or not duplicate_ids:
                        continue

                    # Avoid processing nodes already seen as primary or duplicate
                    if primary_id in seen_ids:
                        continue

                    filtered_dupes = [
                        d
                        for d in duplicate_ids
                        if d not in seen_ids and d != primary_id
                    ]
                    if not filtered_dupes:
                        continue

                    fact_ids = [primary_id, *filtered_dupes]
                    try:
                        result_id = await merge_duplicates_with_retry(
                            db, fact_ids, owner_id=owner_id
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Dedup job: failed to merge group for primary %s: %s",
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
                        if merged_groups == 1 or merged_groups % 10 == 0:
                            logger.info(
                                "Dedup job: sample merge #%d - primary=%s, merged %d facts",
                                merged_groups,
                                primary_id,
                                len(filtered_dupes),
                            )
                    else:
                        failed_groups += 1

                elapsed_time = time.time() - start_time
                logger.info(
                    "Dedup job finished (owner_id=%s): merged_groups=%d, merged_facts=%d, failed_groups=%d, "
                    "elapsed_time=%.2fs",
                    owner_id,
                    merged_groups,
                    merged_facts,
                    failed_groups,
                    elapsed_time,
                )

            # Also deduplicate Entity nodes
            try:
                ent_groups = await find_entity_duplicates_with_retry(
                    db,
                    threshold,
                    max_group_size,
                    owner_id=owner_id,
                    hours_threshold=hours_threshold,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Dedup job: failed to find duplicate entity groups (owner_id=%s): %s",
                    owner_id,
                    exc,
                )
                continue

            if not ent_groups:
                logger.info(
                    "Dedup job: no duplicate entity groups found (owner_id=%s)",
                    owner_id,
                )
            else:
                merged_entity_groups = 0
                failed_entity_groups = 0
                seen_entity_ids = set()

                for group in ent_groups:
                    primary_id = group.get("primary_id")
                    duplicate_ids = group.get("duplicate_ids") or []
                    if not primary_id or not duplicate_ids:
                        continue

                    if primary_id in seen_entity_ids:
                        continue

                    filtered_dupes = [
                        d
                        for d in duplicate_ids
                        if d not in seen_entity_ids and d != primary_id
                    ]
                    if not filtered_dupes:
                        continue

                    ent_ids = [primary_id, *filtered_dupes]
                    try:
                        result_id = await merge_entity_duplicates_with_retry(
                            db, entity_ids=ent_ids, owner_id=owner_id
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

        finally:
            if lock_context is not None:
                lock_context.__exit__(None, None, None)
