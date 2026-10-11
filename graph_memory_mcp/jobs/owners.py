"""Which owners a background job runs for."""

from __future__ import annotations

import logging

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.utils import normalize_owner_id

logger = logging.getLogger(__name__)


def parse_owner_ids(config: MCPServerConfig) -> list[str]:
    """Owners named in JOBS_OWNER_IDS. Empty when the setting is unset."""
    raw = (config.jobs_owner_ids or "").strip()
    owners: list[str] = []
    for part in raw.split(","):
        text = part.strip()
        if not text:
            continue
        try:
            owners.append(normalize_owner_id(text))
        except ValueError:
            logger.warning("Jobs: skipping invalid owner_id %r", text)
    return owners


def resolve_owner_ids(db, config: MCPServerConfig) -> list[str]:
    """JOBS_OWNER_IDS limits jobs to those tenants. Unset means every owner."""
    listed = parse_owner_ids(config)
    raw = (config.jobs_owner_ids or "").strip()
    if raw and not config.jobs_process_all_owners:
        return listed

    try:
        discovered = db.list_owners()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jobs: failed to discover owners: %s", exc)
        return listed

    owners: list[str] = []
    for owner_text in discovered:
        try:
            owners.append(normalize_owner_id(owner_text))
        except ValueError:
            logger.warning("Jobs: skipping invalid owner_id %r", owner_text)

    return sorted(set(owners)) or listed
