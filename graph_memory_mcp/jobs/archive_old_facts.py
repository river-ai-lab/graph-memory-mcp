import logging
import time
from typing import Any, Dict, List

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory import mcp_handlers_nodes
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.utils import normalize_owner_id
from graph_memory_mcp.jobs.lock import job_lock
from graph_memory_mcp.jobs.retry import retry_async

logger = logging.getLogger(__name__)


def _parse_owner_ids(config: MCPServerConfig) -> List[str]:
    """Parse owner IDs from config."""
    raw = config.jobs_owner_ids or "default"
    owners = [o.strip() for o in raw.split(",") if o.strip()]
    return owners or ["default"]


async def _execute_query(
    db: FalkorDBClient,
    query: str,
    params: Dict[str, Any] | None = None,
) -> Any:
    """Execute graph query with retry logic."""
    result = db.graph.query(query, params=params)
    if not result or not hasattr(result, "result_set"):
        return None
    # Return in old format for compatibility: [header, rows]
    return [result.header if hasattr(result, "header") else [], result.result_set]


async def archive_old_facts(db: FalkorDBClient, config: MCPServerConfig) -> None:
    """
    Background job: archive facts with expired TTL.
    """
    if not config.enabled:
        logger.info("Archive job: memory server is disabled in config, skipping")
        return

    if not config.jobs_enabled or not config.job_archive_enabled:
        logger.info("Archive job: disabled, skipping")
        return

    retry_max_attempts = config.job_retry_max_attempts
    retry_backoff_base = config.job_retry_backoff_base
    retry_backoff_max = config.job_retry_backoff_max

    execute_query_with_retry = retry_async(
        max_attempts=retry_max_attempts,
        backoff_base=retry_backoff_base,
        backoff_max=retry_backoff_max,
    )(_execute_query)

    owners = _parse_owner_ids(config)
    lock_ttl = config.jobs_lock_ttl_seconds

    # Fact.created_at / expires_at are stored in milliseconds (timestamp())
    now_ms = int(time.time() * 1000)
    logger.info("Archive job: scanning for expired TTL facts (now_ms=%s)", now_ms)

    for owner_id in owners:
        lock_key = f"graph_memory_mcp:job:archive_old_facts:{owner_id}"

        # Note: db.redis_client might not exist in new architecture
        # For now, skip locking if redis not available
        if not hasattr(db, "redis_client") or db.redis_client is None:
            logger.warning("Archive job: Redis not available, running without lock")
            acquired = True
            lock_context = None
        else:
            lock_context = job_lock(db.redis_client, lock_key, ttl_seconds=lock_ttl)
            acquired = lock_context.__enter__()

        try:
            if not acquired:
                logger.info(
                    "Archive job: lock busy for owner_id=%s, skipping", owner_id
                )
                continue

            owner_id_normalized = normalize_owner_id(owner_id)

            # 1) Find candidates: expired TTL only, status active only
            params = {"owner_id": owner_id_normalized, "now_ms": now_ms}
            query = """
            MATCH (f:Fact)
            WHERE f.owner_id = $owner_id
              AND (f.status IS NULL OR f.status = 'active')
              AND (f.expires_at IS NOT NULL AND f.expires_at <= $now_ms)
            RETURN id(f) as fact_id
            """

            try:
                result = await execute_query_with_retry(db, query, params)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Archive job: failed to query candidates (owner_id=%s): %s",
                    owner_id,
                    exc,
                )
                continue

            if not result or len(result) <= 1 or not result[1]:
                logger.info("Archive job: no candidates found (owner_id=%s)", owner_id)
                continue

            candidate_ids: List[int] = [row[0] for row in result[1] if row]

            archived_count = 0
            skipped_active_relations = 0
            skipped_status = 0

            for raw_id in candidate_ids:
                fact_id = str(raw_id)

                # 2) Load the fact and check status == "active"
                try:
                    fact_result = mcp_handlers_nodes.get_node(
                        db, node_id=fact_id, owner_id=owner_id
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Archive job: failed to get fact %s (owner_id=%s): %s",
                        fact_id,
                        owner_id,
                        exc,
                    )
                    continue

                if not fact_result.get("success"):
                    continue

                fact = fact_result.get("node")
                if not fact:
                    continue

                status = fact.get("status", "active")
                if status != "active":
                    skipped_status += 1
                    continue

                metadata = fact.get("metadata") or {}
                if not isinstance(metadata, dict):
                    metadata = {}

                # 3) Ensure there are no "active relationships"
                rel_query = """
                MATCH (f:Fact)-[r]-(n)
                WHERE id(f) = $raw_id
                RETURN labels(n) as n_labels, n.status as n_status
                """

                try:
                    rel_result = await execute_query_with_retry(
                        db, rel_query, {"raw_id": raw_id}
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Archive job: failed to query relations for fact %s: %s",
                        fact_id,
                        exc,
                    )
                    continue

                has_active_neighbour = False
                if rel_result and len(rel_result) > 1 and rel_result[1]:
                    for row in rel_result[1]:
                        if not row:
                            continue
                        n_labels = row[0]
                        n_status = row[1] if len(row) > 1 else None

                        # normalize bytes
                        if isinstance(n_status, bytes):
                            n_status = n_status.decode("utf-8", errors="replace")

                        # FalkorDB may return labels as list/array
                        labels_list = []
                        if isinstance(n_labels, list):
                            for lbl in n_labels:
                                if isinstance(lbl, bytes):
                                    labels_list.append(
                                        lbl.decode("utf-8", errors="replace")
                                    )
                                else:
                                    labels_list.append(str(lbl))
                        elif isinstance(n_labels, bytes):
                            labels_list = [n_labels.decode("utf-8", errors="replace")]
                        elif isinstance(n_labels, str):
                            labels_list = [n_labels]

                        if labels_list and "Entity" in labels_list:
                            has_active_neighbour = True
                            break
                        if labels_list and "Fact" in labels_list:
                            if n_status is None or n_status == "active":
                                has_active_neighbour = True
                                break

                if has_active_neighbour:
                    skipped_active_relations += 1
                    continue

                # 4) Archive: set n.status = "archived"
                reason = metadata.get("status_reason")
                if not reason:
                    metadata["status_reason"] = "archived_by_cleanup_job"

                try:
                    updated_result = mcp_handlers_nodes.update_node(
                        db,
                        node_id=fact_id,
                        status="archived",
                        metadata=metadata,
                        owner_id=owner_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Archive job: failed to archive fact %s: %s", fact_id, exc
                    )
                    continue

                if updated_result.get("success"):
                    archived_count += 1

            logger.info(
                "Archive job finished (owner_id=%s): archived=%s, skipped_status=%s, "
                "skipped_due_to_active_relations=%s",
                owner_id,
                archived_count,
                skipped_status,
                skipped_active_relations,
            )

        finally:
            if lock_context is not None:
                lock_context.__exit__(None, None, None)
