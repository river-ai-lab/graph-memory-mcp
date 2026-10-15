"""Read-only map captures and GraphDiff analysis; no corporate graph writes."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from graph_memory_mcp.explorer.mcp_client import McpToolClient


def graphdiff_available() -> bool:
    try:
        from graphdiff.memory import capture_memory  # noqa: F401
    except ImportError:
        return False
    return True


def _owner(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_@-]+", value):
        raise ValueError("Valid owner_id is required")
    return value


async def capture_map(client: McpToolClient, body: dict) -> dict:
    from graphdiff.memory import capture_memory

    owner = _owner(body.get("owner_id"))
    ids = body.get("node_ids")
    edges = body.get("edges", [])
    if not isinstance(ids, list) or not 1 <= len(ids) <= 200:
        raise ValueError("Load a map with 1–200 nodes before capturing")
    if len(set(ids)) != len(ids) or not all(
        isinstance(uid, str) and re.fullmatch(r"[a-zA-Z0-9-]{1,64}", uid) for uid in ids
    ):
        raise ValueError("Invalid or duplicate node ids")
    if not isinstance(edges, list) or len(edges) > 10000:
        raise ValueError("Invalid map edges")
    started = datetime.now(timezone.utc)
    nodes = []
    for uid in ids:
        result = await client.call_tool("get_node", {"owner_id": owner, "node_id": uid})
        if result.get("success") is False or not result.get("node"):
            raise ValueError(f"Cannot hydrate node {uid}; reload the map and try again")
        nodes.append(result["node"])
    snapshot = capture_memory(
        {
            "owner_id": owner,
            "coverage": "partial",
            "scope": "loaded-map",
            "nodes": nodes,
            "edges": edges,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {
        "success": True,
        "capture": snapshot.to_dict(),
        "capture_started_at": started.isoformat(),
    }


def activity(body: dict) -> dict:
    from graphdiff.memory import capture_memory, creation_activity

    memory = capture_memory(body["capture"], owner_id=_owner(body.get("owner_id")))
    return {"success": True, **creation_activity(memory, body["start"], body["end"])}


def compare(body: dict) -> dict:
    from graphdiff.memory import capture_memory, compare_memory

    owner = _owner(body.get("owner_id"))
    before = capture_memory(body["before"], owner_id=owner)
    after = capture_memory(body["after"], owner_id=owner)
    return {"success": True, **compare_memory(before, after)}
