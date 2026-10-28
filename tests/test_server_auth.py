"""Auth entry: schemas omit owner_id; the API key supplies it."""

from __future__ import annotations

import asyncio

import pytest

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory.api_keys import create_key
from graph_memory_mcp.graph_memory.owner_scope import (
    bind_api_key,
    configure_owner_scope,
)
from graph_memory_mcp.server import GraphMemoryMCP
from graph_memory_mcp.server_auth import GraphMemoryAuthMCP


class _Emb:
    dimension = 8

    def get_embedding(self, text):  # noqa: ANN001
        return [0.0] * self.dimension

    def get_embeddings_batch(self, texts):  # noqa: ANN001
        return [[0.0] * self.dimension for _ in texts]


@pytest.fixture(autouse=True)
def _reset_scope():
    configure_owner_scope("client")
    yield
    configure_owner_scope("client")


def _open(cls, tmp_path, monkeypatch):
    path = tmp_path / "keys.json"
    record, _raw = create_key(path, "alice", ["p1", "p2"])
    monkeypatch.setenv("OWNER_SCOPE", "token")
    monkeypatch.setenv("ADMIN_TOKEN", "admin-secret")
    monkeypatch.setenv("API_KEYS_FILE", str(path))
    monkeypatch.setenv("MCP_EXPOSE_ADMIN_TOOLS", "true")
    monkeypatch.setattr(
        "graph_memory_mcp.base_server.EmbeddingService",
        lambda *args, **kwargs: _Emb(),
    )
    server = cls(load_mcp_server_config())
    return server, record


def _schemas(server) -> dict[str, dict]:
    return {
        tool.name: tool.parameters for tool in server.mcp._tool_manager.list_tools()
    }


def test_auth_schemas_omit_owner_id_and_keep_agent_fields(tmp_path, monkeypatch):
    auth, _record = _open(GraphMemoryAuthMCP, tmp_path, monkeypatch)
    plain, _record = _open(GraphMemoryMCP, tmp_path, monkeypatch)
    auth_schemas = _schemas(auth)
    plain_schemas = _schemas(plain)

    assert set(auth_schemas) == set(plain_schemas)
    assert "Do not pass it" in auth.mcp.instructions
    assert "first project" not in auth.mcp.instructions
    assert "first project" in plain.mcp.instructions

    removed: list[str] = []
    for name, schema in plain_schemas.items():
        plain_props = set(schema.get("properties") or {})
        auth_props = set(auth_schemas[name].get("properties") or {})
        assert "created_by" not in plain_props
        assert "created_by" not in auth_props
        if "owner_id" in plain_props:
            assert auth_props == plain_props - {"owner_id"}
            assert "owner_id" not in (auth_schemas[name].get("required") or [])
            removed.append(name)
        else:
            assert auth_props == plain_props
    assert "search" in removed
    assert "create_node" in removed
    assert "import_owner" in removed
    assert "health_check" not in removed
    assert "metadata" in auth_schemas["create_node"]["properties"]
    assert "metadata_filter" in auth_schemas["search"]["properties"]
    assert "properties" in auth_schemas["create_relation"]["properties"]
    assert "nodes" in auth_schemas["import_owner"]["required"]


def test_auth_resolves_owner_from_the_key(tmp_path, monkeypatch):
    server, record = _open(GraphMemoryAuthMCP, tmp_path, monkeypatch)
    seen: list[str] = []

    def label_counts(owner_id):
        seen.append(owner_id)
        return []

    server.db_client.label_counts = label_counts
    server.db_client.fact_status_counts = lambda owner_id: []
    server.db_client.relation_count = lambda owner_id: [[0]]
    tool = next(
        item
        for item in server.mcp._tool_manager.list_tools()
        if item.name == "get_stats"
    )

    with bind_api_key(record):
        direct = server.get_stats()
        ignored = server.get_stats(owner_id="p2")
        via_schema = asyncio.run(tool.run({}, None))
        via_extra = asyncio.run(tool.run({"owner_id": "p2"}, None))

    assert seen == ["p1", "p1", "p1", "p1"]
    for result in (direct, ignored, via_schema, via_extra):
        assert result["success"] is True


def test_cli_auth_forces_token_scope(monkeypatch):
    import uvicorn

    from graph_memory_mcp.cli import main

    monkeypatch.setenv("OWNER_SCOPE", "client")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    started: dict[str, str] = {}

    class _Server:
        def __init__(self, config):
            started["scope"] = config.owner_scope

        def get_mcp_app(self):
            return "app"

    monkeypatch.setattr(
        "graph_memory_mcp.server_auth.GraphMemoryAuthMCP",
        _Server,
    )
    monkeypatch.setattr(
        uvicorn, "run", lambda app, **kwargs: started.update(host=kwargs["host"])
    )
    main(["--auth", "--host", "0.0.0.0"])
    assert started == {"scope": "token", "host": "0.0.0.0"}


def test_cli_auth_does_not_apply_header_bind_rules(monkeypatch):
    import uvicorn

    from graph_memory_mcp.cli import main

    monkeypatch.setenv("OWNER_SCOPE", "header")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    monkeypatch.delenv("ALLOW_INSECURE_HEADER", raising=False)
    started: dict[str, str] = {}

    class _Server:
        def __init__(self, config):
            started["scope"] = config.owner_scope

        def get_mcp_app(self):
            return "app"

    monkeypatch.setattr(
        "graph_memory_mcp.server_auth.GraphMemoryAuthMCP",
        _Server,
    )
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    main(["--auth", "--host", "0.0.0.0"])
    assert started["scope"] == "token"


def test_cli_auth_refuses_to_start_without_a_token(monkeypatch, tmp_path):
    from graph_memory_mcp.cli import main

    monkeypatch.setenv("OWNER_SCOPE", "client")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    monkeypatch.setenv("API_KEYS_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(SystemExit) as exc:
        main(["--auth"])
    assert "ADMIN_TOKEN" in str(exc.value)


def test_cli_auth_is_exclusive_with_simple():
    from graph_memory_mcp.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["--auth", "--simple"])
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "cls_path", ["server", "server_simple", "server_extended", "server_auth"]
)
def test_tool_descriptions_carry_generated_policy(cls_path, tmp_path, monkeypatch):
    import importlib

    from graph_memory_mcp.resources.policy_generated import TOOL_RULES

    module = importlib.import_module(f"graph_memory_mcp.{cls_path}")
    cls = {
        "server": "GraphMemoryMCP",
        "server_simple": "GraphMemorySimpleMCP",
        "server_extended": "GraphMemoryExtendedMCP",
        "server_auth": "GraphMemoryAuthMCP",
    }[cls_path]
    server, _record = _open(getattr(module, cls), tmp_path, monkeypatch)
    tools = {t.name: t.description for t in server.mcp._tool_manager.list_tools()}
    present = [name for name in TOOL_RULES if name in tools]
    assert "create_node" in present
    for name in present:
        assert tools[name].endswith(f"Policy: {TOOL_RULES[name]}")
        assert tools[name].count("Policy:") == 1
