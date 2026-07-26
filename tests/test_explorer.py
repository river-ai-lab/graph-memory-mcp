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
    for name in (
        "api.js",
        "detail.js",
        "dom.js",
        "graph.js",
        "interactions.js",
        "neighbors.js",
        "panel.js",
        "persist.js",
        "state.js",
        "tools.js",
    ):
        assert (STATIC_DIR / "js" / name).is_file(), name


def test_read_only_tools_include_graph_reads():
    assert "get_context" in READ_ONLY_TOOLS
    assert "recall_context" in READ_ONLY_TOOLS
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
        assert 'id="btn-brief"' in page.text
        assert 'id="llm-tool"' in page.text
        assert 'id="btn-run-tool"' in page.text
        assert 'id="params-recall_context"' in page.text
        assert 'id="params-get_trace"' in page.text
        assert 'id="scope-project"' in page.text
        assert 'id="scope-tags"' in page.text
        assert 'id="scope-outdated"' in page.text
        assert 'id="tool-hint"' in page.text
        assert "field-hint" in page.text
        assert 'id="btn-reset-forms"' in page.text
        assert 'id="btn-copy-id"' in page.text
        assert 'id="btn-copy-raw"' in page.text
        assert 'id="btn-json"' in page.text
        assert 'id="params-search_triplets"' in page.text
        assert 'id="params-get_stats"' in page.text
        assert 'id="btn-neighbors"' in page.text
        assert 'id="btn-neighbors-more"' in page.text
        assert 'id="sel-action"' in page.text
        assert 'id="btn-sel-neighbors"' in page.text
        assert 'id="layout-mode"' in page.text
        assert 'id="btn-layout"' in page.text
        assert 'id="btn-rotate-cw"' in page.text
        assert 'id="view-fact"' in page.text
        assert 'id="btn-history"' in page.text
        assert 'id="tool-raw"' in page.text
        assert "recall-outdated" not in page.text
        assert "ctx-outdated" not in page.text

        assert 'type="module"' in page.text

        static = client.get("/static/explorer.js")
        assert static.status_code == 200
        assert "./js/graph.js" in static.text
        assert "initCy" in static.text
        assert "bindPanelControls" in static.text

        neighbors = client.get("/static/js/neighbors.js")
        assert neighbors.status_code == 200
        assert "emptyNeighborInfo" in neighbors.text
        assert "revealNeighborPage" in neighbors.text
        assert "fetchCap" in neighbors.text
        assert "bufferIds" in neighbors.text
        assert "loadNeighbors" in neighbors.text

        graph_js = client.get("/static/js/graph.js")
        assert graph_js.status_code == 200
        assert "export function syncGraph" in graph_js.text
        assert "export function initCy" in graph_js.text
        assert "exportJson" in graph_js.text
        assert "edge-contradicts" in graph_js.text

        tools_js = client.get("/static/js/tools.js")
        assert tools_js.status_code == 200
        assert "runSelectedTool" in tools_js.text
        assert "AbortController" in tools_js.text
        assert "recall_context" in tools_js.text
        assert "search_triplets" in tools_js.text
        assert "get_stats" in tools_js.text

        persist_js = client.get("/static/js/persist.js")
        assert persist_js.status_code == 200
        assert "loadPersistedFields" in persist_js.text
        assert "resetPersistedForms" in persist_js.text
        assert "TOOL_HINTS" in persist_js.text

        api_js = client.get("/static/js/api.js")
        assert api_js.status_code == 200
        assert "scopeIncludeOutdated" in api_js.text
        assert "export async function callTool" in api_js.text

        detail_js = client.get("/static/js/detail.js")
        assert detail_js.status_code == 200
        assert "get_brief" in detail_js.text
        assert "loadBrief" in detail_js.text


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
