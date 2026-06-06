"""Tests for Graph Memory Explorer (read-only tool proxy + static UI)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.explorer.app import READ_ONLY_TOOLS, STATIC_DIR, create_app
from graph_memory_mcp.explorer.mcp_client import McpHttpClient


class _MockMcpClient:
    url = "mock://test"
    connected = True

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.connected = False

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if name == "health_check":
            return {"success": True, "falkordb": True}
        if name == "get_stats":
            return {"success": True, "stats": {"total_nodes": 3}}
        raise ValueError(f"unexpected tool: {name}")


def test_static_assets_exist():
    assert (STATIC_DIR / "index.html").is_file()
    assert (STATIC_DIR / "explorer.js").is_file()
    assert (STATIC_DIR / "explorer.css").is_file()


def test_read_only_tools_include_graph_reads():
    assert "get_context" in READ_ONLY_TOOLS
    assert "find_similar" in READ_ONLY_TOOLS
    assert "create_node" not in READ_ONLY_TOOLS


def test_explorer_api_with_mock_client():
    app = create_app(_MockMcpClient())
    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health["ready"] is True
        assert health["mcp_url"] == "mock://test"

        tools = client.get("/api/tools").json()
        assert "get_context" in tools["tools"]

        blocked = client.post(
            "/api/tool", json={"tool": "create_node", "arguments": {}}
        )
        assert blocked.status_code == 403

        ok = client.post(
            "/api/tool",
            json={"tool": "get_stats", "arguments": {"owner_id": "default"}},
        )
        assert ok.status_code == 200
        assert ok.json()["stats"]["total_nodes"] == 3

        page = client.get("/")
        assert page.status_code == 200
        assert "Graph Memory Explorer" in page.text

        static = client.get("/static/explorer.js")
        assert static.status_code == 200
        assert "callTool" in static.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_explorer_live_get_stats():
    cfg = load_mcp_server_config()

    from graph_memory_mcp.server import GraphMemoryMCP

    server = GraphMemoryMCP(cfg)
    if not server._db_connected:
        pytest.fail("FalkorDB connection failed")

    mcp_app = server.get_mcp_app()

    async with server.mcp.session_manager.run():
        http_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mcp_app),
            base_url="http://127.0.0.1:8000",
        )
        mcp_client = McpHttpClient("http://127.0.0.1:8000/mcp", http_client=http_client)
        app = create_app(mcp_client)
        with TestClient(app) as client:
            health = client.get("/health").json()
            assert health["ready"] is True

            stats = client.post(
                "/api/tool",
                json={"tool": "get_stats", "arguments": {"owner_id": "default"}},
            ).json()
            assert stats.get("success") is True
            assert "stats" in stats

            ctx = client.post(
                "/api/tool",
                json={
                    "tool": "get_context",
                    "arguments": {
                        "node_id": "1",
                        "owner_id": "default",
                        "depth": 1,
                        "max_nodes": 5,
                    },
                },
            )
            assert ctx.status_code == 200
            body = ctx.json()
            assert body.get("success") is True or "nodes" in body
