import logging
import time
from typing import Any, Dict, List

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.utils import (
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
    """Resolve owner IDs from config or discover them from per-owner graphs."""
    if not config.jobs_process_all_owners:
        return _parse_owner_ids(config)

    try:
        discovered = db.list_owners()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Dedup job: failed to discover owners, falling back to jobs_owner_ids: %s",
            exc,
        )
        return _parse_owner_ids(config)

    owners = []
    for owner_text in discovered:
        try:
            owners.append(normalize_owner_id(owner_text))
        except ValueError:
            logger.warning("Dedup job: skipping invalid owner_id %r", owner_text)

    return sorted(set(owners)) or _parse_owner_ids(config)


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

    rows = db.dedup_candidate_rows(
        label=label, owner_id=owner_id, limit=limit, touched_filter=touched_filter
    )
    if not rows:
        return []
    return _parse_candidate_rows(rows)


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
    """ANN (HNSW) neighbor lookup for one candidate, owner/status post-filtered.

    ~O(log N + k) per candidate via the existing vector index — replaces the
    former exact scan over the whole owner corpus. The index is global per
    label, so `ann_k` takes a margin to survive the post-ANN owner filter.
    """
    ann_k = min(max(top_k * 2, 100), 2000)
    rows = db.dedup_similar_rows(
        label=label,
        embedding=[float(v) for v in embedding],
        max_distance=1.0 - threshold,
        owner_id=owner_id,
        node_id=str(node_id),
        ann_k=ann_k,
        top_k=top_k,
    )
    return [
        {
            "node_id": str(row[0]),
            "created_at": row[1] or 0,
            "score": float(row[2]),
        }
        for row in rows
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
    """Find duplicate groups: ANN pairs per candidate, union-find into components.

    Union-find merges overlapping candidate neighborhoods into disjoint groups,
    so each node appears in at most one group and the oldest member becomes
    the primary of its whole connected component.
    """
    owner_id = normalize_owner_id(owner_id)
    candidates = candidates or _load_dedup_candidates(
        db,
        label=label,
        owner_id=owner_id,
        hours_threshold=hours_threshold,
    )
    if not candidates:
        return []

    try:
        db.ensure_vector_indexes_if_missing(owner_id=owner_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dedup: failed to ensure vector indexes: %s", exc)

    top_k = max(max_group_size, getattr(db.config, "duplicate_top_k", 100))

    parent: Dict[str, str] = {}
    created_at_by_id: Dict[str, Any] = {}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        root_a, root_b = _find(a), _find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    def _record(node_id: str, created_at: Any) -> None:
        known = created_at_by_id.get(node_id)
        if known is None or (created_at or 0) < (known or 0):
            created_at_by_id[node_id] = created_at or 0

    for candidate in candidates:
        cand_id = str(candidate["node_id"])
        _record(cand_id, candidate.get("created_at"))
        matches = _query_similar_nodes(
            db,
            label=label,
            node_id=cand_id,
            embedding=candidate["embedding"],
            owner_id=owner_id,
            threshold=threshold,
            top_k=top_k,
        )
        for match in matches:
            match_id = str(match["node_id"])
            _record(match_id, match.get("created_at"))
            _union(cand_id, match_id)

    components: Dict[str, List[str]] = {}
    for node_id in parent:
        components.setdefault(_find(node_id), []).append(node_id)

    groups: List[Dict[str, Any]] = []
    for members in components.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda nid: (created_at_by_id.get(nid, 0), nid))
        primary_id = members[0]
        duplicate_ids = members[1 : max(2, max_group_size)]
        groups.append({"primary_id": primary_id, "duplicate_ids": duplicate_ids})

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

    db.mark_deduped(
        label=label,
        node_ids=[str(node_id) for node_id in node_ids],
        owner_id=normalize_owner_id(owner_id),
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


def _merge_duplicate_nodes(
    db: FalkorDBClient,
    *,
    label: str,
    node_ids: List[str],
    owner_id: str,
) -> str | None:
    """Merge duplicates: redirect relations to the primary, mark others outdated.

    Not transactional (FalkorDB executes one query atomically); instead the
    steps are idempotent (MERGE-based) and ordered so a partial failure is
    repaired by the next dedup run. Duplicates get `merged_into` for tracing.

    Returns primary node ID.
    """
    if not node_ids or len(node_ids) < 2:
        return None

    owner_id = normalize_owner_id(owner_id)
    primary_id = str(node_ids[0])
    duplicate_ids = [str(node_id) for node_id in node_ids[1:]]

    for dup_id in duplicate_ids:
        try:
            for row in db.rels_out(label=label, dup_id=dup_id, owner_id=owner_id):
                rel_type, props, target_id = row
                db.copy_rel_out(
                    label=label,
                    rel_type=rel_type,
                    params={
                        "primary_id": primary_id,
                        "target_id": str(target_id),
                        "props": props,
                        "owner_id": owner_id,
                    },
                )
            db.delete_rels_out(label=label, dup_id=dup_id, owner_id=owner_id)
        except Exception as e:
            logger.warning(f"Failed to redirect outgoing relations for {dup_id}: {e}")

        try:
            for row in db.rels_in(label=label, dup_id=dup_id, owner_id=owner_id):
                rel_type, props, source_id = row
                db.copy_rel_in(
                    label=label,
                    rel_type=rel_type,
                    params={
                        "source_id": str(source_id),
                        "primary_id": primary_id,
                        "props": props,
                        "owner_id": owner_id,
                    },
                )
            db.delete_rels_in(label=label, dup_id=dup_id, owner_id=owner_id)
        except Exception as e:
            logger.warning(f"Failed to redirect incoming relations for {dup_id}: {e}")

        try:
            # merged_into makes partially-failed merges traceable and re-runnable.
            db.mark_merged(
                label=label,
                dup_id=dup_id,
                primary_id=primary_id,
                owner_id=owner_id,
            )
        except Exception as e:
            logger.warning(f"Failed to mark {dup_id} as outdated: {e}")

    try:
        db.touch_dedup_primary(
            label=label, primary_id=primary_id, owner_id=owner_id
        )
    except Exception as e:
        logger.warning(f"Failed to update last_dedup_at for primary {primary_id}: {e}")

    return primary_id


async def _merge_duplicate_facts(
    db: FalkorDBClient,
    fact_ids: List[str],
    owner_id: str,
) -> str | None:
    """Merge duplicate facts. Returns primary fact ID."""
    return _merge_duplicate_nodes(
        db, label="Fact", node_ids=fact_ids, owner_id=owner_id
    )


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
    """Merge duplicate entities. Returns primary entity ID."""
    return _merge_duplicate_nodes(
        db, label="Entity", node_ids=entity_ids, owner_id=owner_id
    )


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

    threshold = config.job_deduplicate_similarity_threshold
    max_group_size = max(2, config.duplicate_max_group_size)
    hours_threshold = config.job_deduplicate_hours_threshold

    lock_ttl = config.jobs_lock_ttl_seconds
    owners = _resolve_owner_ids(db, config)

    for owner_id in owners:
        lock_key = f"graph_memory_mcp:job:deduplicate_facts:{owner_id}"

        if db.redis_client is None:
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
