"""Vela backend: embedded Kuzu fork, no FalkorDB."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.backends import open_store
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.mcp_handlers_admin import export_owner, get_stats, import_owner
from graph_memory_mcp.graph_memory.mcp_handlers_graph import get_trace
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import create_node, get_node, update_node
from graph_memory_mcp.graph_memory.mcp_handlers_relations import create_relation, create_triplet
from graph_memory_mcp.graph_memory.mcp_handlers_search import search

pytestmark = pytest.mark.vela


class _Embeddings:
    dimension = 4

    def get_embedding(self, text: str, kind: str = "passage") -> list[float]:
        del kind
        if "alpha" in (text or "").lower():
            return [1.0, 0.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0, 0.0]

    def get_embeddings_batch(self, texts: list[str], kind: str = "passage") -> list[list[float]]:
        return [self.get_embedding(text, kind) for text in texts]

    def ping(self) -> bool:
        return True


def _config(tmp_path) -> MCPServerConfig:
    return MCPServerConfig(
        graph_backend="vela",
        vela_path=str(tmp_path),
        vela_graph="memory",
    )


def _store(tmp_path):
    db = open_store(_config(tmp_path))
    db.set_embedding_service(_Embeddings())
    return db


def test_default_backend_stays_falkordb(monkeypatch):
    monkeypatch.delenv("GRAPH_BACKEND", raising=False)
    cfg = MCPServerConfig(_env_file=None)
    assert cfg.graph_backend == "falkordb"
    assert FalkorDBClient.__name__ == "FalkorDBClient"


def test_open_store_rejects_unknown_backend():
    with pytest.raises(ValueError, match="vela"):
        open_store(SimpleNamespace(graph_backend="neo4j"))


def test_open_store_falkor_remains_the_default_factory(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(
        "graph_memory_mcp.graph_memory.backends.FalkorDBClient",
        lambda config: sentinel,
    )
    assert open_store(SimpleNamespace(graph_backend="falkordb")) is sentinel
    assert open_store(SimpleNamespace()) is sentinel


def test_create_search_relate_and_isolate(tmp_path):
    db = _store(tmp_path)
    cfg = db.config
    owner = f"vela_{uuid.uuid4().hex[:8]}"
    other = f"vela_{uuid.uuid4().hex[:8]}"

    assert db.connect() is True
    health = db.health_check()
    assert health["status"] == "healthy"
    assert health["vela_connected"] is True
    assert health.get("falkordb_connected") is not True

    created = create_node(
        db,
        cfg,
        text="alpha memory fact",
        owner_id=owner,
        metadata={"project": "vela"},
    )
    assert created["success"] is True, created
    node_id = created["node"]["node_id"]

    other_fact = create_node(db, cfg, text="beta other fact", owner_id=owner)
    assert other_fact["success"] is True

    fetched = get_node(db, node_id=node_id, owner_id=owner)
    assert fetched["success"] is True
    assert fetched["node"]["text"] == "alpha memory fact"
    assert fetched["node"]["metadata"]["project"] == "vela"

    hidden = get_node(db, node_id=node_id, owner_id=other)
    assert hidden["success"] is False

    found = search(db, cfg, query="alpha memory fact", owner_id=owner, limit=5)
    assert found["success"] is True
    ids = [row["node_id"] for row in found["facts"]]
    assert node_id in ids
    assert other_fact["node"]["node_id"] not in ids

    linked = create_relation(
        db,
        from_id=node_id,
        to_id=other_fact["node"]["node_id"],
        relation_type="RELATED_TO",
        properties={"strength": 0.9},
        owner_id=owner,
        config=cfg,
    )
    assert linked["success"] is True, linked
    again = create_relation(
        db,
        from_id=node_id,
        to_id=other_fact["node"]["node_id"],
        relation_type="RELATED_TO",
        properties={"strength": 0.9},
        owner_id=owner,
        config=cfg,
    )
    assert again["success"] is True

    edges = db.edges_between([node_id, other_fact["node"]["node_id"]], owner)
    assert len(edges) == 1
    assert edges[0][1] == "RELATED_TO"
    assert edges[0][3]["strength"] == 0.9

    trace = get_trace(
        db,
        from_id=node_id,
        to_id=other_fact["node"]["node_id"],
        owner_id=owner,
    )
    assert trace["success"] is True
    assert [node["node_id"] for node in trace["nodes"]] == [
        node_id,
        other_fact["node"]["node_id"],
    ]

    stats = get_stats(db, owner_id=owner)
    assert stats["stats"]["total_facts"] == 2
    assert stats["stats"]["total_relations"] == 1

    triplet = create_triplet(
        db,
        subject="Alpha",
        predicate="USES",
        object_value="Vela",
        owner_id=owner,
        config=cfg,
    )
    assert triplet["success"] is True, triplet
    assert triplet["triplet"]["predicate"] == "USES"

    exported = export_owner(db, owner_id=owner, include_embeddings=True)
    assert exported["success"] is True
    assert exported["node_count"] >= 2
    copied = import_owner(
        db,
        owner_id=other,
        nodes=exported["nodes"],
        relations=exported["relations"],
    )
    assert copied["success"] is True, copied
    copied_node = get_node(db, node_id=node_id, owner_id=other)
    assert copied_node["success"] is True
    assert copied_node["node"]["text"] == "alpha memory fact"

    updated = update_node(db, node_id=node_id, owner_id=owner, text="alpha memory revised")
    assert updated["success"] is True
    assert updated["node"]["text"] == "alpha memory revised"

    assert owner in db.list_owners()
    assert db.delete_owner_graph(owner) is True
    assert owner not in db.list_owners()
    assert other in db.list_owners()
