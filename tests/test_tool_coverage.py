"""Every registered MCP tool is listed here and called by name at least once."""

from __future__ import annotations

import json
import uuid

import pytest

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory.api_keys import create_key
from graph_memory_mcp.graph_memory.owner_scope import configure_owner_scope
from graph_memory_mcp.server import GraphMemoryMCP
from graph_memory_mcp.server_auth import GraphMemoryAuthMCP
from graph_memory_mcp.server_extended import GraphMemoryExtendedMCP
from graph_memory_mcp.server_simple import GraphMemorySimpleMCP

ADMIN_TOOLS = {
    "test_connection",
    "ensure_vector_indexes",
    "export_owner",
    "import_owner",
}
DEFAULT_TOOLS = {
    "get_stats",
    "health_check",
    "get_brief",
    "create_node",
    "upsert_node",
    "update_node",
    "ingest_knowledge",
    "create_nodes",
    "search",
    "get_node",
    "delete_node",
    "mark_outdated",
    "get_node_change_history",
    "create_triplet",
    "search_triplets",
    "create_relation",
    "get_trace",
    "delete_relation",
    "get_context",
    "recall_context",
    "find_similar",
    "create_summary_fact",
}
ALL_TOOLS = DEFAULT_TOOLS | ADMIN_TOOLS
VARIANTS = [
    GraphMemoryMCP,
    GraphMemorySimpleMCP,
    GraphMemoryExtendedMCP,
    GraphMemoryAuthMCP,
]


def _config(backend: str = "falkordb", **update):
    cfg = load_mcp_server_config().model_copy(
        update={"graph_backend": backend, **update}
    )
    if backend == "arcadedb":
        cfg = cfg.model_copy(update={"arcade_password": "playwithdata"})
    return cfg


def _tool_names(server) -> set[str]:
    return {tool.name for tool in server.mcp._tool_manager.list_tools()}


def _server(variant, admin: bool, tmp_path):
    update = {"mcp_expose_admin_tools": admin}
    if variant is GraphMemoryAuthMCP:
        keys = tmp_path / "keys.json"
        create_key(keys, "alice", ["p1"])
        update.update(admin_token="admin-secret", api_keys_file=str(keys))
    try:
        return variant(_config(**update))
    finally:
        configure_owner_scope("client")


@pytest.mark.parametrize("variant", VARIANTS, ids=lambda cls: cls.__name__)
@pytest.mark.parametrize("admin", [False, True], ids=["default", "admin"])
def test_variant_registers_exactly_the_known_tools(variant, admin, tmp_path):
    server = _server(variant, admin, tmp_path)
    assert _tool_names(server) == (ALL_TOOLS if admin else DEFAULT_TOOLS)


HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


@pytest.mark.parametrize("variant", VARIANTS, ids=lambda cls: cls.__name__)
def test_every_tool_declares_all_four_hints(variant, tmp_path):
    server = _server(variant, True, tmp_path)
    for tool in server.mcp._tool_manager.list_tools():
        hints = tool.annotations.model_dump(by_alias=True) if tool.annotations else {}
        missing = [h for h in HINTS if not isinstance(hints.get(h), bool)]
        assert not missing, (tool.name, missing)
        assert hints["openWorldHint"] is False, tool.name
        if hints["readOnlyHint"]:
            assert hints["destructiveHint"] is False, tool.name


def _payload(result) -> dict:
    """Return the JSON dict of a FastMCP ``call_tool`` result."""
    if isinstance(result, tuple):
        content, structured = result
        if isinstance(structured, dict):
            return structured.get("result", structured)
        result = content
    blocks = getattr(result, "content", result)
    return json.loads(blocks[0].text)


@pytest.fixture(
    scope="module",
    params=["falkordb", pytest.param("arcadedb", marks=pytest.mark.arcade)],
)
def admin_server(request):
    return GraphMemoryMCP(_config(request.param, mcp_expose_admin_tools=True))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_every_tool_runs_by_name(admin_server):
    """Smoke-call each tool once; together the calls cover ALL_TOOLS."""
    called: set[str] = set()
    owner = f"pytest_tools_{uuid.uuid4().hex[:8]}"

    async def call(name: str, **args) -> dict:
        called.add(name)
        data = _payload(await admin_server.mcp.call_tool(name, args))
        assert data.get("success") is not False, (name, data)
        return data

    def node_id(data: dict) -> str:
        return data["node"]["node_id"]

    await call("test_connection")
    await call("health_check")
    await call("ensure_vector_indexes")

    a = node_id(
        await call("create_node", text="Coverage uses FalkorDB", owner_id=owner)
    )
    b = node_id(
        await call(
            "create_node",
            text="Lunch is served at noon in the cafeteria",
            owner_id=owner,
        )
    )
    await call(
        "upsert_node",
        text="Coverage anchor",
        source={"ref": "coverage-anchor"},
        owner_id=owner,
    )
    await call(
        "update_node", node_id=a, text="Coverage uses FalkorDB 4", owner_id=owner
    )
    await call(
        "create_nodes",
        items=[{"text": "Bulk fact one"}, {"text": "Bulk fact two"}],
        owner_id=owner,
    )
    await call(
        "ingest_knowledge",
        document={"title": "Coverage doc", "ref": "coverage-doc"},
        facts=[{"text": "Ingested coverage fact"}],
        owner_id=owner,
    )
    await call(
        "create_relation",
        from_id=a,
        to_id=b,
        relation_type="RELATED_TO",
        owner_id=owner,
    )
    await call("get_trace", from_id=a, to_id=b, owner_id=owner)
    await call("get_context", node_id=a, owner_id=owner)
    await call("delete_relation", from_id=a, to_id=b, owner_id=owner)
    await call(
        "create_triplet",
        subject="Coverage",
        predicate="USES",
        object_value="Pytest",
        owner_id=owner,
    )
    await call("search_triplets", subject="Coverage", owner_id=owner)
    await call("search", query="coverage database", owner_id=owner)
    await call("recall_context", query="coverage database", owner_id=owner)
    await call("find_similar", fact_id=a, owner_id=owner)
    await call("get_node", node_id=a, owner_id=owner)
    await call("get_node_change_history", node_id=a, owner_id=owner)
    await call(
        "create_summary_fact",
        fact_ids=[a, b],
        summary_text="Coverage runs on both backends",
        owner_id=owner,
    )
    await call("get_brief", owner_id=owner)
    await call("get_stats", owner_id=owner)

    exported = await call("export_owner", owner_id=owner, include_embeddings=False)
    await call(
        "import_owner",
        owner_id=f"{owner}_copy",
        nodes=exported["nodes"],
        relations=exported.get("relations") or [],
        regenerate_embeddings=True,
    )

    await call("mark_outdated", fact_id=b, reason="coverage", owner_id=owner)
    await call("delete_node", node_id=a, owner_id=owner)

    assert called == ALL_TOOLS
