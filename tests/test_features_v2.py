"""Tests for metadata filters, bulk create, export/import, time-aware recall, metrics."""

from __future__ import annotations

import time
import uuid

import pytest

from graph_memory_mcp.config import MCPServerConfig, load_mcp_server_config
from graph_memory_mcp.graph_memory import mcp_handlers_admin as admin
from graph_memory_mcp.graph_memory import mcp_handlers_nodes as nodes
from graph_memory_mcp.graph_memory import mcp_handlers_search as search_mod
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import metadata_promoted_props
from graph_memory_mcp.graph_memory.owner_scoped_search import (
    build_metadata_filter_clauses,
)


@pytest.fixture(scope="module")
def db_client():
    cfg = load_mcp_server_config()
    db = FalkorDBClient(cfg)
    if not db.connect():
        pytest.fail("FalkorDB connection failed")
    db.set_embedding_service(EmbeddingService(model_name=cfg.embedding_model))
    return db


def test_metadata_promoted_props():
    props = metadata_promoted_props(
        {
            "tags": ["a", "b"],
            "type": "regulation",
            "confidence": 0.9,
            "project": "apollo",
            "created_by": "agent:codegen",
            "extra": 1,
        }
    )
    assert props == {
        "tags": ["a", "b"],
        "meta_type": "regulation",
        "confidence": 0.9,
        "project": "apollo",
        "created_by": "agent:codegen",
    }
    assert metadata_promoted_props(None) == {
        "tags": None,
        "meta_type": None,
        "confidence": None,
        "project": None,
        "created_by": None,
    }


def test_metadata_reserved_keys_reject_wrong_types():
    with pytest.raises(ValueError):
        metadata_promoted_props({"confidence": "high"})
    with pytest.raises(ValueError):
        metadata_promoted_props({"project": ["not", "a", "string"]})
    # Free-form extra keys never fail validation.
    assert metadata_promoted_props({"anything": {"nested": True}})["project"] is None


def test_create_node_rejects_invalid_reserved_metadata(db_client):
    cfg = load_mcp_server_config()
    result = nodes.create_node(
        db_client,
        cfg,
        text="bad metadata",
        owner_id="default",
        metadata={"confidence": "high"},
        auto_link=False,
    )
    assert result["success"] is False
    assert result["code"] == "memory_validation_error"


def test_metadata_filter_clauses_and_validation():
    clauses, params = build_metadata_filter_clauses(
        {"type": "t", "tags": ["x"], "confidence_min": 0.5}
    )
    assert "node.meta_type = $mf_type" in clauses
    assert "$mf_tag0 IN node.tags" in clauses
    assert "node.confidence >= $mf_conf" in clauses
    assert params == {"mf_type": "t", "mf_tag0": "x", "mf_conf": 0.5}

    with pytest.raises(ValueError):
        build_metadata_filter_clauses({"bogus": 1})


def test_search_rejects_unknown_metadata_filter_key(db_client):
    cfg = load_mcp_server_config()
    result = search_mod.search(
        db_client, cfg, query="q", owner_id="default", metadata_filter={"nope": 1}
    )
    assert result["success"] is False
    assert result["code"] == "memory_validation_error"


@pytest.mark.integration
@pytest.mark.parametrize("search_type", ["pre_filter", "post_filter"])
def test_search_metadata_filter(db_client, search_type):
    cfg = load_mcp_server_config()
    owner = f"pytest_mf_{uuid.uuid4().hex[:8]}"
    text = f"metadata filter probe {uuid.uuid4().hex[:8]}"

    tagged = nodes.create_node(
        db_client,
        cfg,
        text=text,
        owner_id=owner,
        metadata={"type": "regulation", "tags": ["critical"], "confidence": 0.9},
        auto_link=False,
    )
    untagged = nodes.create_node(
        db_client, cfg, text=text + " other", owner_id=owner, auto_link=False
    )
    assert tagged["success"] and untagged["success"]

    result = search_mod.search(
        db_client,
        cfg,
        query=text,
        owner_id=owner,
        similarity_threshold=0.2,
        search_type=search_type,
        metadata_filter={
            "type": "regulation",
            "tags": "critical",
            "confidence_min": 0.5,
        },
    )
    ids = {r["node_id"] for r in result["results"]}
    assert tagged["node"]["node_id"] in ids
    assert untagged["node"]["node_id"] not in ids


@pytest.mark.integration
def test_project_scoping_filter(db_client):
    """owner is the wall, project is a filter: scoped and cross-project reads."""
    cfg = load_mcp_server_config()
    owner = f"pytest_scope_{uuid.uuid4().hex[:8]}"
    probe = f"scoping probe {uuid.uuid4().hex[:8]}"

    in_apollo = nodes.create_node(
        db_client,
        cfg,
        text=f"{probe} apollo",
        owner_id=owner,
        metadata={"project": "apollo", "created_by": "agent:one"},
        auto_link=False,
    )["node"]["node_id"]
    in_zeus = nodes.create_node(
        db_client,
        cfg,
        text=f"{probe} zeus",
        owner_id=owner,
        metadata={"project": "zeus", "created_by": "agent:two"},
        auto_link=False,
    )["node"]["node_id"]

    scoped = search_mod.search(
        db_client,
        cfg,
        query=probe,
        owner_id=owner,
        similarity_threshold=0.2,
        metadata_filter={"project": "apollo"},
    )
    ids = {r["node_id"] for r in scoped["results"]}
    assert in_apollo in ids and in_zeus not in ids

    by_author = search_mod.search(
        db_client,
        cfg,
        query=probe,
        owner_id=owner,
        similarity_threshold=0.2,
        metadata_filter={"created_by": "agent:two"},
    )
    ids = {r["node_id"] for r in by_author["results"]}
    assert in_zeus in ids and in_apollo not in ids

    # Cross-project recall: just omit the filter.
    all_projects = search_mod.search(
        db_client, cfg, query=probe, owner_id=owner, similarity_threshold=0.2
    )
    ids = {r["node_id"] for r in all_projects["results"]}
    assert {in_apollo, in_zeus} <= ids


@pytest.mark.integration
def test_update_node_repromotes_metadata(db_client):
    cfg = load_mcp_server_config()
    owner = f"pytest_mfu_{uuid.uuid4().hex[:8]}"
    created = nodes.create_node(
        db_client, cfg, text="promote me", owner_id=owner, auto_link=False
    )
    node_id = created["node"]["node_id"]
    updated = nodes.update_node(
        db_client, node_id=node_id, owner_id=owner, metadata={"type": "decision"}
    )
    assert updated["success"]
    r = db_client.query(
        "MATCH (n) WHERE n.uid=$u RETURN n.meta_type",
        params={"u": node_id, "owner_id": owner},
    )
    assert r.result_set[0][0] == "decision"


@pytest.mark.integration
def test_create_nodes_bulk(db_client):
    cfg = load_mcp_server_config()
    owner = f"pytest_bulk_{uuid.uuid4().hex[:8]}"
    items = [
        {"text": f"bulk fact {i} {uuid.uuid4().hex[:6]}", "metadata": {"tags": ["b"]}}
        for i in range(5)
    ]
    result = nodes.create_nodes(db_client, cfg, items=items, owner_id=owner)
    assert result["success"] is True
    assert result["count"] == 5

    got = nodes.get_node(
        db_client, node_id=result["nodes"][0]["node_id"], owner_id=owner
    )
    assert got["success"] and got["node"]["text"] == items[0]["text"]

    found = search_mod.search(
        db_client,
        cfg,
        query="bulk fact",
        owner_id=owner,
        similarity_threshold=0.2,
        metadata_filter={"tags": "b"},
    )
    assert len(found["results"]) >= 5


def test_create_nodes_validation(db_client):
    cfg = MCPServerConfig()
    assert (
        nodes.create_nodes(db_client, cfg, items=[], owner_id="default")["code"]
        == "memory_validation_error"
    )
    assert (
        nodes.create_nodes(db_client, cfg, items=[{"nope": 1}], owner_id="default")[
            "code"
        ]
        == "memory_validation_error"
    )


@pytest.mark.integration
def test_export_import_roundtrip(db_client):
    cfg = load_mcp_server_config()
    src = f"pytest_exp_{uuid.uuid4().hex[:8]}"
    dst = f"{src}_copy"

    a = nodes.create_node(
        db_client, cfg, text="export fact A", owner_id=src, auto_link=False
    )["node"]["node_id"]
    b = nodes.create_node(
        db_client,
        cfg,
        text="export entity B",
        node_type="Entity",
        owner_id=src,
        auto_link=False,
    )["node"]["node_id"]
    from graph_memory_mcp.graph_memory import mcp_handlers_relations as rel

    rel.create_relation(
        db_client,
        from_id=a,
        to_id=b,
        relation_type="MENTIONS",
        owner_id=src,
        config=cfg,
    )

    exported = admin.export_owner(db_client, owner_id=src)
    assert exported["success"]
    assert exported["node_count"] == 2 and exported["relation_count"] == 1
    assert exported["nodes"][0]["properties"].get("embedding"), "embeddings exported"

    imported = admin.import_owner(
        db_client,
        owner_id=dst,
        nodes=exported["nodes"],
        relations=exported["relations"],
    )
    assert imported["success"]
    assert imported["imported_nodes"] == 2 and imported["imported_relations"] == 1

    got = nodes.get_node(db_client, node_id=a, owner_id=dst)
    assert got["success"] and got["node"]["text"] == "export fact A"

    found = search_mod.search(
        db_client, cfg, query="export fact", owner_id=dst, similarity_threshold=0.2
    )
    assert any(r["node_id"] == a for r in found["results"])

    # idempotent re-import
    again = admin.import_owner(
        db_client,
        owner_id=dst,
        nodes=exported["nodes"],
        relations=exported["relations"],
    )
    assert again["success"]
    stats = admin.get_stats(db_client, owner_id=dst)
    assert stats["stats"]["total_nodes"] == 2


@pytest.mark.integration
def test_get_node_as_of(db_client):
    cfg = load_mcp_server_config()
    owner = f"pytest_asof_{uuid.uuid4().hex[:8]}"
    created = nodes.create_node(
        db_client, cfg, text="version one", owner_id=owner, auto_link=False
    )
    node_id = created["node"]["node_id"]
    time.sleep(0.05)
    t_between = int(time.time() * 1000)
    time.sleep(0.05)
    nodes.update_node(
        db_client,
        node_id=node_id,
        owner_id=owner,
        text="version two",
        versioning=True,
    )

    now_state = nodes.get_node(db_client, node_id=node_id, owner_id=owner)
    assert now_state["node"]["text"] == "version two"

    past_state = nodes.get_node(
        db_client, node_id=node_id, owner_id=owner, as_of=t_between
    )
    assert past_state["success"] and past_state["as_of"] == t_between
    assert past_state["node"]["text"] == "version one"

    before_create = nodes.get_node(db_client, node_id=node_id, owner_id=owner, as_of=1)
    assert before_create["success"] is False
    assert before_create["code"] == "memory_not_found"


def test_time_aware_factor_defaults():
    from graph_memory_mcp.graph_memory.mcp_handlers_graph import _time_aware_factor

    cfg = MCPServerConfig()
    now_ms = int(time.time() * 1000)
    fresh = _time_aware_factor(cfg, touched_at_ms=now_ms, access_count=0)
    old = _time_aware_factor(
        cfg, touched_at_ms=now_ms - 365 * 86_400_000, access_count=0
    )
    assert fresh > old
    used = _time_aware_factor(cfg, touched_at_ms=now_ms, access_count=100)
    assert used > fresh

    off = MCPServerConfig(recall_recency_weight=0.0, recall_usage_weight=0.0)
    assert _time_aware_factor(off, touched_at_ms=1, access_count=0) == 1.0


@pytest.mark.integration
def test_metrics_endpoint(db_client):
    from starlette.testclient import TestClient

    from graph_memory_mcp.server import GraphMemoryMCP

    cfg = load_mcp_server_config()
    server = GraphMemoryMCP(cfg)
    app = server.get_mcp_app()
    with TestClient(app) as client:
        resp = client.get("/metrics")
        assert resp.status_code == 200
        body = resp.text
        assert "graph_memory_handler_seconds" in body
        assert "graph_memory_nodes" in body


@pytest.mark.integration
def test_admin_routes_and_agent_tool_separation(db_client, monkeypatch):
    """Admin ops live on /admin/*; agent MCP does not expose them by default."""
    from starlette.testclient import TestClient

    from graph_memory_mcp.server import GraphMemoryMCP

    monkeypatch.delenv("MCP_EXPOSE_ADMIN_TOOLS", raising=False)
    cfg = load_mcp_server_config()
    server = GraphMemoryMCP(cfg)

    # Admin-only tools are not registered as MCP tools by default...
    for admin_tool in (
        "test_connection",
        "ensure_vector_indexes",
        "export_owner",
        "import_owner",
    ):
        assert not hasattr(server, admin_tool)
    # ...while agent tools are.
    for agent_tool in ("search", "create_node", "get_brief", "recall_context"):
        assert hasattr(server, agent_tool)

    owner = f"pytest_admin_{uuid.uuid4().hex[:8]}"
    nodes.create_node(
        db_client,
        load_mcp_server_config(),
        text="admin route fact",
        owner_id=owner,
        auto_link=False,
    )

    app = server.get_mcp_app()
    with TestClient(app) as client:
        assert client.get("/admin/health").json()["success"] is True
        assert client.post("/admin/ensure-indexes").json()["success"] is True

        exported = client.get(f"/admin/export/{owner}").json()
        assert exported["success"] is True and exported["node_count"] == 1

        imported = client.post(
            "/admin/import",
            json={"owner_id": f"{owner}_copy", "nodes": exported["nodes"]},
        ).json()
        assert imported["success"] is True and imported["imported_nodes"] == 1


@pytest.mark.integration
def test_admin_routes_require_token_when_set(db_client, monkeypatch):
    from starlette.testclient import TestClient

    from graph_memory_mcp.server import GraphMemoryMCP

    monkeypatch.setenv("ADMIN_TOKEN", "secret123")
    cfg = load_mcp_server_config()
    server = GraphMemoryMCP(cfg)
    app = server.get_mcp_app()
    with TestClient(app) as client:
        assert client.get("/admin/health").status_code == 401
        ok = client.get("/admin/health", headers={"Authorization": "Bearer secret123"})
        assert ok.status_code == 200 and ok.json()["success"] is True


def test_embedding_prefixes_config(monkeypatch):
    from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService

    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "query: ")
    monkeypatch.setenv("EMBEDDING_PASSAGE_PREFIX", "passage: ")
    cfg = load_mcp_server_config()
    assert cfg.embedding_query_prefix == "query: "
    assert cfg.embedding_passage_prefix == "passage: "

    svc = EmbeddingService.__new__(EmbeddingService)
    svc.query_prefix = cfg.embedding_query_prefix
    svc.passage_prefix = cfg.embedding_passage_prefix
    assert svc._prefix("where is redis", "query") == "query: where is redis"
    assert svc._prefix("redis is at host X", "passage") == "passage: redis is at host X"
