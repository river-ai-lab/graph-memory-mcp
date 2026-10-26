"""--auth over streamable HTTP: no owner_id argument, key picks the owner."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import PaginatedRequestParams

from graph_memory_mcp import __version__
from graph_memory_mcp.graph_memory.api_keys import create_key
from graph_memory_mcp.graph_memory.mcp_handlers_graph import get_context
from graph_memory_mcp.server import GraphMemoryMCP
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


def _fact_count(db, owner_id: str) -> int:
    for row in db.label_counts(owner_id):
        if row[0] == "Fact":
            return int(row[1])
    return 0


@pytest.mark.asyncio
async def test_token_mode_create_node_omits_owner_id(tmp_path, memory_backend):
    """Token mode keeps owner_id in the schema. Omitting it uses the first project."""
    primary = f"tokp{uuid.uuid4().hex[:8]}"
    other = f"tokq{uuid.uuid4().hex[:8]}"
    _record, raw = create_key(tmp_path / "keys.json", "alice", [primary, other])
    cfg = memory_backend.config.model_copy(
        update={
            "owner_scope": "token",
            "admin_token": "admin-secret",
            "api_keys_file": str(tmp_path / "keys.json"),
        }
    )
    server = GraphMemoryMCP(cfg)
    app = server.get_mcp_app()
    text = "Token mode stores this fact on the key's first project."
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
                            {"text": text, "check_duplicates": False},
                        )
                    )
                    assert created.get("success") is True, created
                    stats = _tool_json(await session.call_tool("get_stats", {}))
                    assert stats.get("success") is True, stats
                    assert stats["stats"]["total_facts"] >= 1
                    assert _fact_count(server.db_client, primary) >= 1
                    assert _fact_count(server.db_client, other) == 0
    finally:
        server.db_client.delete_owner_graph(primary)
        server.db_client.delete_owner_graph(other)


@pytest.mark.asyncio
async def test_auth_http_tools_use_the_key_without_owner_id(tmp_path, memory_backend):
    """Every listed tool omits owner_id. Writes land in the key's first project."""
    primary = f"authp{uuid.uuid4().hex[:8]}"
    other = f"authq{uuid.uuid4().hex[:8]}"
    _record, raw = create_key(tmp_path / "keys.json", "alice", [primary, other])
    cfg = memory_backend.config.model_copy(
        update={
            "owner_scope": "token",
            "admin_token": "admin-secret",
            "api_keys_file": str(tmp_path / "keys.json"),
            "mcp_expose_admin_tools": True,
        }
    )
    server = GraphMemoryAuthMCP(cfg)
    app = server.get_mcp_app()
    original = "The release deadline is November 1."
    moved = "The release deadline is November 15."

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
                    init = await session.initialize()
                    assert init.server_info.version == __version__

                    tools = []
                    cursor = None
                    while True:
                        page = await session.list_tools(
                            params=None
                            if cursor is None
                            else PaginatedRequestParams(cursor=cursor)
                        )
                        tools.extend(page.tools)
                        cursor = page.next_cursor
                        if not cursor:
                            break
                    names = {tool.name for tool in tools}
                    for tool in tools:
                        props = (tool.input_schema or {}).get("properties") or {}
                        assert "owner_id" not in props, tool.name
                    for name in (
                        "create_node",
                        "update_node",
                        "create_relation",
                        "search",
                        "get_context",
                        "get_node_change_history",
                        "get_stats",
                        "test_connection",
                        "ensure_vector_indexes",
                        "export_owner",
                        "import_owner",
                    ):
                        assert name in names

                    async def call(name: str, arguments: dict | None = None) -> dict:
                        payload = _tool_json(
                            await session.call_tool(name, arguments or {})
                        )
                        assert payload.get("success") is True, payload
                        return payload

                    await call("health_check")
                    await call("test_connection")
                    await call("ensure_vector_indexes")

                    created = await call(
                        "create_node",
                        {
                            "text": original,
                            "node_type": "Fact",
                            "check_duplicates": False,
                        },
                    )
                    fact_id = created["node"]["node_id"]
                    assert created["node"].get("created_by") == "alice"

                    entity = await call(
                        "create_node",
                        {
                            "text": "Release",
                            "node_type": "Entity",
                            "entity_type": "Project",
                        },
                    )
                    entity_id = entity["node"]["node_id"]

                    await call(
                        "update_node",
                        {
                            "node_id": fact_id,
                            "text": moved,
                            "versioning": True,
                        },
                    )
                    history = await call(
                        "get_node_change_history", {"node_id": fact_id}
                    )
                    assert history["count"] == 1
                    assert history["versions"][0]["text"] == original

                    await call(
                        "create_relation",
                        {
                            "from_id": fact_id,
                            "to_id": entity_id,
                            "relation_type": "RELATED_TO",
                        },
                    )
                    # Same get_context as client mode. The key supplies owner_id.
                    context = await call("get_context", {"node_id": fact_id})
                    assert "offset" not in context
                    assert "has_more" not in context
                    assert {node["node_id"] for node in context["nodes"]} >= {
                        fact_id,
                        entity_id,
                    }
                    plain = get_context(
                        server.db_client,
                        server.config,
                        node_id=fact_id,
                        owner_id=primary,
                    )
                    assert plain.get("success") is True, plain

                    def _ids(body: dict) -> list[str]:
                        return [node["node_id"] for node in body["nodes"]]

                    def _edges(body: dict) -> set[tuple[str, str, str]]:
                        return {
                            (edge["from_id"], edge["relation_type"], edge["to_id"])
                            for edge in body["edges"]
                        }

                    assert _ids(context) == _ids(plain)
                    assert _edges(context) == _edges(plain)
                    found = await call(
                        "search",
                        {"query": moved, "limit": 5, "node_types": ["Fact"]},
                    )
                    assert any(row.get("text") == moved for row in found["results"])

                    stats = await call("get_stats")
                    assert stats["stats"]["total_facts"] == _fact_count(
                        server.db_client, primary
                    )
                    assert stats["stats"]["total_facts"] >= 1
                    assert _fact_count(server.db_client, other) == 0

                    exported = await call(
                        "export_owner",
                        {
                            "include_embeddings": False,
                            "include_versions": True,
                        },
                    )
                    assert exported["owner_id"] == primary
                    await call(
                        "import_owner",
                        {
                            "nodes": exported["nodes"],
                            "relations": exported["relations"],
                        },
                    )
                    assert _fact_count(server.db_client, primary) >= 1
                    assert _fact_count(server.db_client, other) == 0
    finally:
        server.db_client.delete_owner_graph(primary)
        server.db_client.delete_owner_graph(other)
