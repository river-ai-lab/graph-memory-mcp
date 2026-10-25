"""Explorer against graph-memory-mcp --auth (no owner_id on tools)."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.testclient import TestClient

from graph_memory_mcp.explorer.app import create_app
from graph_memory_mcp.explorer.mcp_client import McpHttpClient
from graph_memory_mcp.graph_memory.api_keys import create_key
from graph_memory_mcp.server_auth import GraphMemoryAuthMCP


def _tool_json(result) -> dict:
    for block in getattr(result, "content", None) or []:
        data = getattr(block, "json", None)
        if isinstance(data, dict):
            return data
        text = getattr(block, "text", None)
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
            if isinstance(parsed, dict):
                return parsed
    return {"raw": repr(result)}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_explorer_auth_mode_strips_owner_and_reads_graph(
    tmp_path, memory_backend
):
    owner = f"expauth{uuid.uuid4().hex[:8]}"
    _record, raw = create_key(tmp_path / "keys.json", "explorer", [owner])
    cfg = memory_backend.config.model_copy(
        update={
            "owner_scope": "token",
            "admin_token": "admin-secret",
            "api_keys_file": str(tmp_path / "keys.json"),
        }
    )
    server = GraphMemoryAuthMCP(cfg)
    app = server.get_mcp_app()
    try:
        async with server.mcp.session_manager.run():
            async with streamable_http_client(
                "http://127.0.0.1:8000/mcp",
                http_client=httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://127.0.0.1:8000",
                    headers={"Authorization": f"Bearer {raw}"},
                ),
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    created = _tool_json(
                        await session.call_tool(
                            "create_node",
                            {
                                "text": "Deadline is November 1.",
                                "check_duplicates": False,
                            },
                        )
                    )
                    assert created.get("success") is True, created
                    node_id = created["node"]["node_id"]

            http_client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1:8000",
                headers={"Authorization": f"Bearer {raw}"},
            )
            mcp_client = McpHttpClient(
                "http://127.0.0.1:8000/mcp",
                http_client=http_client,
                headers={"Authorization": f"Bearer {raw}"},
                hide_owner=True,
            )
            explorer = create_app(mcp_client)
            with TestClient(explorer) as client:
                health = client.get("/health").json()
                assert health["ready"] is True
                assert health["hide_owner"] is True
                assert health["auth"] is True

                stats = client.post(
                    "/api/tool",
                    json={
                        "tool": "get_stats",
                        "arguments": {"owner_id": "ignored-by-auth"},
                    },
                ).json()
                assert stats.get("success") is True, stats
                assert stats["stats"]["total_facts"] >= 1

                node = client.post(
                    "/api/tool",
                    json={
                        "tool": "get_node",
                        "arguments": {
                            "node_id": node_id,
                            "owner_id": "should-be-stripped",
                        },
                    },
                ).json()
                assert node.get("success") is True, node
                assert node["node"]["text"] == "Deadline is November 1."
                assert node["node"].get("status") == "active"
                assert node["node"].get("created_at") is not None
    finally:
        server.db_client.delete_owner_graph(owner)
