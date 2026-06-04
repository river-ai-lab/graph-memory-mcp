"""Tests for relation type allowlist and enforcement."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, cast

import httpx
import pytest
import redis
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import create_node
from graph_memory_mcp.graph_memory.mcp_handlers_relations import (
    create_relation,
    create_triplet,
)
from graph_memory_mcp.graph_memory.relation_policy import (
    AUTO_LINK_RELATION,
    DEFAULT_RELATION_ALLOWED_TYPES,
    allowed_relation_types,
    effective_relation_config,
    evaluate_relation_policy,
    parse_allowed_relation_types,
    relation_policy_mode,
)
from graph_memory_mcp.server import GraphMemoryMCP


@dataclass
class _PolicyConfig:
    relation_policy_enforce: str = "warn"
    relation_allowed_types: str = ",".join(DEFAULT_RELATION_ALLOWED_TYPES)


class _FakeGraph:
    def query(self, query, params=None):
        return type("R", (), {"result_set": [[1]]})()


class _FakeCache:
    def invalidate_search(self) -> None:
        pass


class _FakeDB:
    graph = _FakeGraph()
    cache = _FakeCache()


def _falkordb_is_available(host: str, port: int, password: str | None) -> bool:
    try:
        client = redis.Redis(
            host=host, port=port, password=password, socket_timeout=0.5
        )
        return client.ping() is True
    except Exception:
        return False


def _extract_tool_json(result) -> dict:
    content = getattr(result, "content", None)
    if content and len(content) > 0:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            import json

            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
    return {}


def _strict_policy_config():
    base = load_mcp_server_config()
    return base.model_copy(
        update={
            "relation_policy_enforce": "enforce",
            "relation_allowed_types": "RELATED_TO",
        }
    )


def test_auto_link_relation_constant():
    assert AUTO_LINK_RELATION == "MENTIONS"


def test_parse_allowed_relation_types():
    parsed = parse_allowed_relation_types("RELATED_TO, mentions ,CUSTOM")
    assert parsed == frozenset({"RELATED_TO", "MENTIONS", "CUSTOM"})


def test_evaluate_policy_off():
    cfg = _PolicyConfig(relation_policy_enforce="off")
    proceed, warning, error = evaluate_relation_policy(cfg, "NOT_IN_LIST")
    assert proceed is True
    assert warning is None
    assert error is None


def test_evaluate_policy_warn():
    cfg = _PolicyConfig(
        relation_policy_enforce="warn",
        relation_allowed_types="RELATED_TO",
    )
    proceed, warning, error = evaluate_relation_policy(cfg, "MENTIONS")
    assert proceed is True
    assert warning is not None
    assert "MENTIONS" in warning
    assert error is None


def test_evaluate_policy_enforce():
    cfg = _PolicyConfig(
        relation_policy_enforce="enforce",
        relation_allowed_types="RELATED_TO",
    )
    proceed, warning, error = evaluate_relation_policy(cfg, "MENTIONS")
    assert proceed is False
    assert warning is None
    assert error is not None


def test_system_relation_extracted_from_always_allowed():
    cfg = _PolicyConfig(
        relation_policy_enforce="enforce",
        relation_allowed_types="RELATED_TO",
    )
    proceed, warning, error = evaluate_relation_policy(
        cfg, "EXTRACTED_FROM", internal=True
    )
    assert proceed is True
    assert warning is None
    assert error is None


def test_none_config_uses_effective_server_config():
    cfg = effective_relation_config(None)
    assert relation_policy_mode(cfg) in {"off", "warn", "enforce"}
    assert "RELATED_TO" in allowed_relation_types(cfg)


def test_create_relation_enforce_blocks_disallowed_type():
    cfg = _PolicyConfig(
        relation_policy_enforce="enforce",
        relation_allowed_types="RELATED_TO",
    )
    result = create_relation(
        cast(Any, _FakeDB()),
        from_id="1",
        to_id="2",
        relation_type="MENTIONS",
        owner_id="demo",
        config=cfg,
    )
    assert result["success"] is False
    assert result["code"] == "memory_relation_policy_error"


def test_create_relation_warn_allows_with_warning():
    cfg = _PolicyConfig(
        relation_policy_enforce="warn",
        relation_allowed_types="RELATED_TO",
    )
    result = create_relation(
        cast(Any, _FakeDB()),
        from_id="1",
        to_id="2",
        relation_type="MENTIONS",
        owner_id="demo",
        config=cfg,
    )
    assert result["success"] is True
    assert result["relation_type"] == "MENTIONS"
    assert "warning" in result


def test_create_relation_allowed_type_no_warning():
    cfg = _PolicyConfig(relation_policy_enforce="warn")
    result = create_relation(
        cast(Any, _FakeDB()),
        from_id="1",
        to_id="2",
        relation_type="RELATED_TO",
        owner_id="demo",
        config=cfg,
    )
    assert result["success"] is True
    assert "warning" not in result


def test_create_triplet_enforce_blocks_disallowed_predicate():
    cfg = _PolicyConfig(
        relation_policy_enforce="enforce",
        relation_allowed_types="RELATED_TO",
    )
    result = create_triplet(
        cast(Any, _FakeDB()),
        subject="A",
        predicate="RUNS_ON",
        object_value="B",
        owner_id="demo",
        config=cfg,
    )
    assert result["success"] is False
    assert result["code"] == "memory_relation_policy_error"


@pytest.mark.integration
def test_create_node_links_surface_policy_errors():
    if os.environ.get("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("integration tests disabled")

    cfg = _strict_policy_config()
    if not _falkordb_is_available(
        cfg.falkordb_host, cfg.falkordb_port, cfg.falkordb_password
    ):
        pytest.skip("FalkorDB unavailable")

    db = FalkorDBClient(cfg)
    if not db.connect():
        pytest.skip("FalkorDB connection failed")
    db.set_embedding_service(EmbeddingService(model_name=cfg.embedding_model))

    owner_id = f"pytest_link_policy_{uuid.uuid4().hex[:8]}"
    target = create_node(
        db,
        cfg,
        text="link policy target",
        node_type="Fact",
        owner_id=owner_id,
        auto_link=False,
    )
    target_id = target["node"]["node_id"]

    result = create_node(
        db,
        cfg,
        text="link policy source",
        node_type="Fact",
        owner_id=owner_id,
        auto_link=False,
        links=[
            {
                "to_id": target_id,
                "relation_type": "MENTIONS",
            }
        ],
    )
    assert result["success"] is True
    assert result.get("link_errors")
    assert result["link_errors"][0]["code"] == "memory_relation_policy_error"


@pytest.mark.integration
def test_auto_link_skipped_under_strict_policy():
    if os.environ.get("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("integration tests disabled")

    cfg = _strict_policy_config()
    if not _falkordb_is_available(
        cfg.falkordb_host, cfg.falkordb_port, cfg.falkordb_password
    ):
        pytest.skip("FalkorDB unavailable")

    db = FalkorDBClient(cfg)
    if not db.connect():
        pytest.skip("FalkorDB connection failed")
    db.set_embedding_service(EmbeddingService(model_name=cfg.embedding_model))

    owner_id = f"pytest_autolink_policy_{uuid.uuid4().hex[:8]}"

    create_node(
        db,
        cfg,
        text="Vector Entity Alpha",
        node_type="Entity",
        owner_id=owner_id,
        auto_link=False,
    )

    fact = create_node(
        db,
        cfg,
        text="Vector Entity Alpha is used in production systems",
        node_type="Fact",
        owner_id=owner_id,
        auto_link=True,
        semantic_threshold=0.5,
    )
    fact_id = fact["node"]["node_id"]

    from graph_memory_mcp.graph_memory.mcp_handlers_graph import get_context

    ctx = get_context(db, cfg, node_id=fact_id, owner_id=owner_id, depth=1)
    mention_edges = [
        e for e in ctx.get("edges", []) if e["relation_type"] == "MENTIONS"
    ]
    assert mention_edges == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_create_relation_policy_enforce():
    if os.environ.get("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("integration tests disabled")

    cfg = _strict_policy_config()
    if not _falkordb_is_available(
        cfg.falkordb_host, cfg.falkordb_port, cfg.falkordb_password
    ):
        pytest.skip("FalkorDB unavailable")

    server = GraphMemoryMCP(cfg)
    if not server._db_connected:
        pytest.skip("FalkorDB connection failed")

    app = server.get_mcp_app()
    owner_id = f"pytest_mcp_policy_{uuid.uuid4().hex[:8]}"

    async with server.mcp.session_manager.run():
        async with streamable_http_client(
            "http://127.0.0.1:8000/mcp",
            http_client=httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1:8000",
            ),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                fact_a = _extract_tool_json(
                    await session.call_tool(
                        "create_node",
                        {
                            "text": "MCP policy fact A",
                            "owner_id": owner_id,
                            "auto_link": False,
                        },
                    )
                )
                fact_b = _extract_tool_json(
                    await session.call_tool(
                        "create_node",
                        {
                            "text": "MCP policy fact B",
                            "owner_id": owner_id,
                            "auto_link": False,
                        },
                    )
                )
                assert fact_a["success"] and fact_b["success"]

                blocked = _extract_tool_json(
                    await session.call_tool(
                        "create_relation",
                        {
                            "from_id": fact_a["node"]["node_id"],
                            "to_id": fact_b["node"]["node_id"],
                            "relation_type": "MENTIONS",
                            "owner_id": owner_id,
                        },
                    )
                )
                assert blocked.get("success") is False
                assert blocked.get("code") == "memory_relation_policy_error"

                allowed = _extract_tool_json(
                    await session.call_tool(
                        "create_relation",
                        {
                            "from_id": fact_a["node"]["node_id"],
                            "to_id": fact_b["node"]["node_id"],
                            "relation_type": "RELATED_TO",
                            "owner_id": owner_id,
                        },
                    )
                )
                assert allowed.get("success") is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_create_triplet_policy_enforce():
    if os.environ.get("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("integration tests disabled")

    cfg = _strict_policy_config()
    if not _falkordb_is_available(
        cfg.falkordb_host, cfg.falkordb_port, cfg.falkordb_password
    ):
        pytest.skip("FalkorDB unavailable")

    server = GraphMemoryMCP(cfg)
    if not server._db_connected:
        pytest.skip("FalkorDB connection failed")

    app = server.get_mcp_app()
    owner_id = f"pytest_mcp_triplet_{uuid.uuid4().hex[:8]}"

    async with server.mcp.session_manager.run():
        async with streamable_http_client(
            "http://127.0.0.1:8000/mcp",
            http_client=httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1:8000",
            ),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                blocked = _extract_tool_json(
                    await session.call_tool(
                        "create_triplet",
                        {
                            "subject": "ServiceA",
                            "predicate": "RUNS_ON",
                            "object_value": "HostB",
                            "owner_id": owner_id,
                        },
                    )
                )
                assert blocked.get("success") is False
                assert blocked.get("code") == "memory_relation_policy_error"
