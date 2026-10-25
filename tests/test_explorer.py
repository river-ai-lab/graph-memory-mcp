"""Tests for Graph Memory Explorer (read-only tool proxy + static UI)."""

from __future__ import annotations

import subprocess
import uuid
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient

from graph_memory_mcp.explorer.app import READ_ONLY_TOOLS, STATIC_DIR, create_app
from graph_memory_mcp.explorer.mcp_client import McpHttpClient
from graph_memory_mcp.graph_memory.mcp_handlers_graph import get_context, get_trace
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import create_node, update_node
from graph_memory_mcp.graph_memory.mcp_handlers_relations import create_relation


class _MockMcpClient:
    url = "mock://test"
    connected = True
    hide_owner = False
    headers: dict[str, str] = {}
    connect_error = None

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
    assert (STATIC_DIR / "logic.js").is_file()


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
        assert 'id="btn-recall"' in page.text
        assert 'id="btn-trace"' in page.text
        assert 'id="search-status"' in page.text
        assert 'id="search-compact"' in page.text
        assert 'id="detail-policy"' in page.text
        assert 'id="node-preview"' in page.text
        assert 'id="detail-when"' in page.text
        assert 'id="node-preview-tip"' in page.text
        assert "On hover" in page.text
        assert "Always" in page.text
        assert "Follows from" in page.text

        health = client.get("/health").json()
        assert health["hide_owner"] is False
        assert health["auth"] is False

        static = client.get("/static/explorer.js")
        assert static.status_code == 200
        assert "callTool" in static.text
        assert "get_brief" in static.text
        assert "get_trace" in static.text
        assert "recall_context" in static.text
        assert "edge-contradicts" in static.text
        assert "edge-follows" in static.text
        assert "contradiction_pairs" in static.text
        assert "include_outdated" in static.text
        assert "gm_node_preview" in client.get("/static/logic.js").text
        assert "valid_from" in client.get("/static/logic.js").text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_explorer_live_get_stats(memory_backend):
    cfg = memory_backend.config

    from graph_memory_mcp.server import GraphMemoryMCP

    server = GraphMemoryMCP(cfg)
    if not server._db_connected:
        pytest.fail(f"{cfg.graph_backend} connection failed")

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


def test_explorer_js_logic_suite():
    result = subprocess.run(
        ["node", "--test", str(STATIC_DIR.parent / "tests" / "logic.test.cjs")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_mcp_client_strips_owner_id_when_hide_owner():
    client = McpHttpClient("http://127.0.0.1:8000/mcp", hide_owner=True)
    assert client.prepare_arguments({"owner_id": "readme_demo", "query": "q"}) == {
        "query": "q"
    }
    open_client = McpHttpClient("http://127.0.0.1:8000/mcp", hide_owner=False)
    assert open_client.prepare_arguments({"owner_id": "readme_demo"}) == {
        "owner_id": "readme_demo"
    }


def test_explorer_health_reports_auth_mode():
    mock = _MockMcpClient()
    mock.hide_owner = True
    mock.headers = {"Authorization": "Bearer test-key"}
    with TestClient(create_app(mock)) as client:
        health = client.get("/health").json()
        assert health["ready"] is True
        assert health["hide_owner"] is True
        assert health["auth"] is True


def test_explorer_cli_auth_requires_token(monkeypatch):
    import sys

    from graph_memory_mcp.explorer import cli

    monkeypatch.delenv("GRAPH_MEMORY_API_KEY", raising=False)
    monkeypatch.delenv("GRAPH_MEMORY_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["graph-memory-explorer", "--auth"])
    with pytest.raises(SystemExit):
        cli.main()


@pytest.mark.integration
def test_get_context_exposes_outdated_status_and_validity(memory_backend):
    cfg = memory_backend.config
    db = memory_backend.db
    owner = f"exp_life_{uuid.uuid4().hex[:8]}"
    current = create_node(
        db,
        cfg,
        text="Beta ships October 20.",
        owner_id=owner,
        check_duplicates=False,
    )["node"]
    old = create_node(
        db,
        cfg,
        text="Beta ships October 1.",
        owner_id=owner,
        metadata={"valid_from": "2026-08-01"},
        check_duplicates=False,
    )["node"]
    updated = update_node(
        db,
        node_id=old["node_id"],
        owner_id=owner,
        status="outdated",
        versioning=True,
        metadata={"valid_until": "2026-10-01"},
    )["node"]
    assert updated["status"] == "outdated"
    create_relation(
        db,
        from_id=current["node_id"],
        to_id=old["node_id"],
        relation_type="FOLLOWS_FROM",
        owner_id=owner,
    )
    hidden = get_context(
        db,
        cfg,
        node_id=current["node_id"],
        owner_id=owner,
        depth=1,
        max_nodes=10,
    )
    assert all(n.get("status") != "outdated" for n in hidden["nodes"])
    shown = get_context(
        db,
        cfg,
        node_id=current["node_id"],
        owner_id=owner,
        depth=1,
        max_nodes=10,
        include_outdated=True,
    )
    by_id = {n["node_id"]: n for n in shown["nodes"]}
    outdated = by_id[old["node_id"]]
    assert outdated["status"] == "outdated"
    assert outdated["text"] == "Beta ships October 1."
    assert (outdated.get("metadata") or {}).get("valid_until") == "2026-10-01"
    assert any(
        e["relation_type"] == "FOLLOWS_FROM"
        and {e["from_id"], e["to_id"]} == {current["node_id"], old["node_id"]}
        for e in shown["edges"]
    )
    traced = get_trace(
        db,
        from_id=current["node_id"],
        to_id=old["node_id"],
        owner_id=owner,
    )
    assert traced["success"] is True
    by_trace = {n["node_id"]: n for n in traced["nodes"]}
    assert by_trace[old["node_id"]]["status"] == "outdated"
    assert by_trace[old["node_id"]]["text"] == "Beta ships October 1."
    assert (by_trace[old["node_id"]].get("metadata") or {}).get("valid_until") == (
        "2026-10-01"
    )
    assert by_trace[old["node_id"]].get("created_at") is not None
    assert traced["relations"][0]["relation_type"] == "FOLLOWS_FROM"
