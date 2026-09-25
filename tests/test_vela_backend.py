"""Vela backend: embedded Kuzu fork, no FalkorDB."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.backends import open_store
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.mcp_handlers_admin import export_owner, get_stats, import_owner
from graph_memory_mcp.graph_memory.mcp_handlers_graph import get_context, get_trace
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import (
    create_node,
    delete_node,
    get_node,
    get_node_change_history,
    update_node,
)
from graph_memory_mcp.graph_memory.mcp_handlers_relations import (
    create_relation,
    create_triplet,
    unlink_facts,
)
from graph_memory_mcp.graph_memory.mcp_handlers_search import find_similar, search

pytestmark = pytest.mark.vela


class _Embeddings:
    dimension = 4

    def get_embedding(self, text: str, kind: str = "passage") -> list[float]:
        del kind
        lowered = (text or "").lower()
        # Unit vectors so cosine distance is exact: near 0, mid 0.2, side 0.4, far 1.
        if "near" in lowered or "alpha" in lowered:
            return [1.0, 0.0, 0.0, 0.0]
        if "mid" in lowered:
            return [0.8, 0.6, 0.0, 0.0]
        if "side" in lowered:
            return [0.6, 0.8, 0.0, 0.0]
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


def _owner() -> str:
    return f"vela_{uuid.uuid4().hex[:8]}"


def _release(db) -> None:
    for holder in list(db._owners.values()):
        db._close_holder(holder)
    db._owners.clear()
    if db._system is not None:
        db._close_holder(db._system)
        db._system = None


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


def test_search_ranks_by_cosine_and_stays_inside_owner(tmp_path):
    db = _store(tmp_path)
    cfg = db.config
    owner = _owner()
    other = _owner()

    near = create_node(
        db, cfg, text="near alpha ranked", owner_id=owner, metadata={"project": "vela"}
    )
    mid = create_node(
        db, cfg, text="mid ranked", owner_id=owner, metadata={"project": "vela"}
    )
    side = create_node(
        db, cfg, text="side ranked", owner_id=owner, metadata={"project": "other"}
    )
    far = create_node(
        db, cfg, text="far beta ranked", owner_id=owner, metadata={"project": "vela"}
    )
    foreign = create_node(
        db, cfg, text="near alpha ranked", owner_id=other, metadata={"project": "vela"}
    )
    assert all(row["success"] for row in (near, mid, side, far, foreign))

    def ranked(search_type=None, metadata_filter=None):
        found = search(
            db,
            cfg,
            query="near alpha",
            owner_id=owner,
            limit=10,
            search_type=search_type,
            metadata_filter=metadata_filter,
        )
        assert found["success"] is True, found
        return found["facts"]

    facts = ranked()
    assert [row["text"] for row in facts] == [
        "near alpha ranked",
        "mid ranked",
        "side ranked",
    ]
    assert facts[0]["similarity"] == pytest.approx(1.0)
    assert facts[1]["similarity"] == pytest.approx(0.8)
    assert facts[2]["similarity"] == pytest.approx(0.6)
    ids = {row["node_id"] for row in facts}
    assert far["node"]["node_id"] not in ids
    assert foreign["node"]["node_id"] not in ids

    same = ranked("post_filter")
    assert [row["node_id"] for row in same] == [row["node_id"] for row in facts]

    vela_only = ranked(metadata_filter={"project": "vela"})
    assert [row["text"] for row in vela_only] == ["near alpha ranked", "mid ranked"]
    other_only = ranked(metadata_filter={"project": "other"})
    assert [row["text"] for row in other_only] == ["side ranked"]

    leaked = search(db, cfg, query="near alpha", owner_id=other, limit=10)
    assert [row["node_id"] for row in leaked["facts"]] == [foreign["node"]["node_id"]]

    similar = find_similar(
        db, cfg, fact_id=near["node"]["node_id"], owner_id=owner, limit=5
    )
    assert similar["success"] is True, similar
    assert [row["text"] for row in similar["similar_facts"]] == ["mid ranked", "side ranked"]
    assert near["node"]["node_id"] not in {
        row["node_id"] for row in similar["similar_facts"]
    }


def test_relations_are_owner_scoped_and_unlink_removes_them(tmp_path):
    db = _store(tmp_path)
    cfg = db.config
    owner = _owner()
    other = _owner()
    left = create_node(db, cfg, text="near alpha left", owner_id=owner)
    right = create_node(db, cfg, text="far beta right", owner_id=other)
    assert left["success"] and right["success"]

    blocked = create_relation(
        db,
        from_id=left["node"]["node_id"],
        to_id=right["node"]["node_id"],
        relation_type="RELATED_TO",
        owner_id=owner,
        config=cfg,
    )
    assert blocked["success"] is False

    peer = create_node(db, cfg, text="far beta peer", owner_id=owner)
    linked = create_relation(
        db,
        from_id=left["node"]["node_id"],
        to_id=peer["node"]["node_id"],
        relation_type="RELATED_TO",
        properties={"strength": 0.4},
        owner_id=owner,
        config=cfg,
    )
    assert linked["success"] is True, linked
    assert db.edges_between(
        [left["node"]["node_id"], peer["node"]["node_id"]], other
    ) == []

    context = get_context(
        db, cfg, node_id=left["node"]["node_id"], owner_id=owner, depth=1
    )
    assert context["success"] is True, context
    assert {node["node_id"] for node in context["nodes"]} == {
        left["node"]["node_id"],
        peer["node"]["node_id"],
    }

    removed = unlink_facts(
        db,
        from_id=left["node"]["node_id"],
        to_id=peer["node"]["node_id"],
        relation_type="RELATED_TO",
        owner_id=owner,
    )
    assert removed["success"] is True
    assert removed["deleted"] == 1
    assert (
        db.edges_between([left["node"]["node_id"], peer["node"]["node_id"]], owner)
        == []
    )
    again = unlink_facts(
        db,
        from_id=left["node"]["node_id"],
        to_id=peer["node"]["node_id"],
        relation_type="RELATED_TO",
        owner_id=owner,
    )
    assert again["deleted"] == 0


def test_update_delete_outdated_and_versions(tmp_path):
    db = _store(tmp_path)
    cfg = db.config
    owner = _owner()
    created = create_node(db, cfg, text="near alpha original", owner_id=owner)
    assert created["success"] is True, created
    node_id = created["node"]["node_id"]
    created_at = created["node"]["created_at"]

    revised = update_node(
        db,
        node_id=node_id,
        owner_id=owner,
        text="near alpha revised",
        versioning=True,
    )
    assert revised["success"] is True, revised
    assert revised["node"]["text"] == "near alpha revised"

    historical = get_node(db, node_id=node_id, owner_id=owner, as_of=created_at)
    assert historical["success"] is True, historical
    assert historical["node"]["text"] == "near alpha original"

    history = get_node_change_history(db, node_id=node_id, owner_id=owner)
    assert history["success"] is True
    assert history["count"] == 1
    assert history["versions"][0]["text"] == "near alpha original"

    outdated = update_node(db, node_id=node_id, owner_id=owner, status="outdated")
    assert outdated["success"] is True
    hidden = search(db, cfg, query="near alpha", owner_id=owner, limit=5)
    assert node_id not in {row["node_id"] for row in hidden["facts"]}
    shown = search(
        db, cfg, query="near alpha", owner_id=owner, limit=5, include_outdated=True
    )
    assert node_id in {row["node_id"] for row in shown["facts"]}

    deleted = delete_node(db, node_id=node_id, owner_id=owner)
    assert deleted["success"] is True, deleted
    missing = get_node(db, node_id=node_id, owner_id=owner)
    assert missing["success"] is False
    assert missing["code"] == "memory_not_found"
    second = delete_node(db, node_id=node_id, owner_id=owner)
    assert second["success"] is False
    assert second["code"] == "memory_not_found"


def test_export_import_keeps_edges_embeddings_and_search(tmp_path):
    db = _store(tmp_path)
    cfg = db.config
    source = _owner()
    target = _owner()
    fact = create_node(
        db, cfg, text="near alpha portable", owner_id=source, metadata={"project": "vela"}
    )
    peer = create_node(db, cfg, text="far beta portable", owner_id=source)
    assert fact["success"] and peer["success"]
    linked = create_relation(
        db,
        from_id=fact["node"]["node_id"],
        to_id=peer["node"]["node_id"],
        relation_type="RELATED_TO",
        properties={"strength": 0.7},
        owner_id=source,
        config=cfg,
    )
    assert linked["success"] is True, linked

    exported = export_owner(db, owner_id=source, include_embeddings=True)
    assert exported["relation_count"] == 1
    assert exported["relations"][0]["properties"]["strength"] == 0.7
    copied = import_owner(
        db,
        owner_id=target,
        nodes=exported["nodes"],
        relations=exported["relations"],
    )
    assert copied["success"] is True, copied
    assert copied["imported_relations"] == 1

    edges = db.edges_between(
        [fact["node"]["node_id"], peer["node"]["node_id"]], target
    )
    assert len(edges) == 1
    assert edges[0][3]["strength"] == 0.7

    found, embedding = db.fact_embedding(fact["node"]["node_id"], target)
    assert found is True
    assert list(embedding) == pytest.approx([1.0, 0.0, 0.0, 0.0])
    hits = search(db, cfg, query="near alpha", owner_id=target, limit=5)
    assert [row["node_id"] for row in hits["facts"]] == [fact["node"]["node_id"]]

    original = get_node(db, node_id=fact["node"]["node_id"], owner_id=source)
    assert original["node"]["text"] == "near alpha portable"


def test_error_paths_and_relation_policy(tmp_path):
    db = _store(tmp_path)
    cfg = db.config
    owner = _owner()
    created = create_node(db, cfg, text="near alpha kept", owner_id=owner)
    assert created["success"] is True
    node_id = created["node"]["node_id"]

    missing_id = uuid.uuid4().hex
    absent = get_node(db, node_id=missing_id, owner_id=owner)
    assert absent["code"] == "memory_not_found"

    bad_owner = create_node(db, cfg, text="near alpha", owner_id="../etc")
    assert bad_owner["success"] is False
    assert bad_owner["code"] == "memory_validation_error"

    bad_search = search(db, cfg, query="near alpha", owner_id=owner, search_type="nope")
    assert bad_search["code"] == "memory_validation_error"

    dangling = create_relation(
        db,
        from_id=node_id,
        to_id=missing_id,
        relation_type="RELATED_TO",
        owner_id=owner,
        config=cfg,
    )
    assert dangling["success"] is False
    assert dangling["code"] == "memory_service_error"

    strict = cfg.model_copy(
        update={
            "relation_policy_enforce": "enforce",
            "relation_allowed_types": "RELATED_TO",
        }
    )
    denied = create_relation(
        db,
        from_id=node_id,
        to_id=node_id,
        relation_type="OWNS",
        owner_id=owner,
        config=strict,
    )
    assert denied["success"] is False
    assert denied["code"] == "memory_relation_policy_error"

    class _Wide(_Embeddings):
        dimension = 8

        def get_embedding(self, text: str, kind: str = "passage") -> list[float]:
            del text, kind
            return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    db.set_embedding_service(_Wide())
    mismatch = create_node(db, cfg, text="near alpha wider", owner_id=owner)
    assert mismatch["success"] is False
    assert mismatch["code"] == "memory_validation_error"
    assert "dimension" in mismatch["error"]


def test_closed_database_reopens_from_disk(tmp_path):
    db = _store(tmp_path)
    cfg = db.config
    owner = _owner()
    created = create_node(db, cfg, text="near alpha durable", owner_id=owner)
    assert created["success"] is True, created
    node_id = created["node"]["node_id"]
    _release(db)

    reopened = _store(tmp_path)
    fetched = get_node(reopened, node_id=node_id, owner_id=owner)
    assert fetched["success"] is True, fetched
    assert fetched["node"]["text"] == "near alpha durable"
    found = search(reopened, cfg, query="near alpha", owner_id=owner, limit=5)
    assert [row["node_id"] for row in found["facts"]] == [node_id]
    assert owner in reopened.list_owners()


def test_health_and_index_status_do_not_invent_owners(tmp_path):
    db = _store(tmp_path)
    assert db.connect() is True
    assert db.health_check()["vela_connected"] is True
    assert db.list_owners() == []
    assert db.get_vector_index_status("nobody") == {"Fact": False, "Entity": False}
    assert db.list_owners() == []
