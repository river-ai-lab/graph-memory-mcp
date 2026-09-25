"""ArcadeDB backend against a running server. FalkorDB is not required."""

from __future__ import annotations

import time
import uuid

import pytest

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.backends import open_store
from graph_memory_mcp.graph_memory.mcp_handlers_admin import (
    export_owner,
    health_check,
    import_owner,
)
from graph_memory_mcp.graph_memory.mcp_handlers_graph import get_context, get_trace
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import (
    create_node,
    delete_node,
    get_node,
    update_node,
)
from graph_memory_mcp.graph_memory.mcp_handlers_relations import (
    create_relation,
    unlink_facts,
)
from graph_memory_mcp.graph_memory.mcp_handlers_search import find_similar, search

pytestmark = pytest.mark.arcade

_DATABASE = "gmarcade"


class _Vectors:
    dimension = 4

    def __init__(self) -> None:
        self._table = {
            "near": [1.0, 0.0, 0.0, 0.0],
            "mid": [0.8, 0.6, 0.0, 0.0],
            "side": [0.6, 0.8, 0.0, 0.0],
            "far": [0.0, 1.0, 0.0, 0.0],
        }

    def get_embedding(self, text: str, kind: str = "passage") -> list[float]:
        del kind
        return list(self._table.get(text, [0.1, 0.2, 0.3, 0.4]))

    def get_embeddings_batch(self, texts: list[str], kind: str = "passage") -> list[list[float]]:
        return [self.get_embedding(text, kind=kind) for text in texts]

    def ping(self) -> bool:
        return True


class _Wide(_Vectors):
    dimension = 8

    def get_embedding(self, text: str, kind: str = "passage") -> list[float]:
        del text, kind
        return [0.1] * 8


def _owner() -> str:
    return "o" + uuid.uuid4().hex[:12]


def _config(**overrides) -> MCPServerConfig:
    values = {
        "graph_backend": "arcadedb",
        "arcade_host": "127.0.0.1",
        "arcade_port": 2480,
        "arcade_user": "root",
        "arcade_password": "playwithdata",
        "arcade_database": _DATABASE,
    }
    values.update(overrides)
    return MCPServerConfig(**values)


@pytest.fixture(scope="module")
def store():
    db = open_store(_config())
    db.drop_database()
    db.set_embedding_service(_Vectors())
    assert db.connect() is True
    yield db
    db.drop_database()


def _create(store, config, owner_id: str, text: str, **kwargs):
    result = create_node(
        store,
        config,
        text=text,
        owner_id=owner_id,
        auto_link=False,
        **kwargs,
    )
    assert result["success"], result
    return result["node"]


def test_default_backend_stays_falkordb(monkeypatch):
    created = {}

    class Fake:
        def __init__(self, config):
            created["config"] = config

    monkeypatch.setattr(
        "graph_memory_mcp.graph_memory.backends.FalkorDBClient", Fake
    )
    config = MCPServerConfig()
    assert config.graph_backend == "falkordb"
    opened = open_store(config)
    assert isinstance(opened, Fake)
    assert created["config"] is config


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError, match="arcadedb"):
        open_store(MCPServerConfig(graph_backend="kuzu"))


def test_create_get_update_delete(store):
    config = _config()
    owner_id = _owner()
    node = _create(store, config, owner_id, "near", description="d")
    fetched = get_node(store, node_id=node["node_id"], owner_id=owner_id)
    assert fetched["success"]
    assert fetched["node"]["text"] == "near"
    assert fetched["node"]["description"] == "d"

    updated = update_node(
        store, node_id=node["node_id"], owner_id=owner_id, description="changed"
    )
    assert updated["success"]
    assert updated["node"]["description"] == "changed"

    removed = delete_node(store, node_id=node["node_id"], owner_id=owner_id)
    assert removed["success"]
    missing = get_node(store, node_id=node["node_id"], owner_id=owner_id)
    assert missing["code"] == "memory_not_found"


def test_search_uses_index_for_both_modes(store):
    config = _config()
    owner_id = _owner()
    for text in ("near", "mid", "side", "far"):
        _create(store, config, owner_id, text)

    for search_type in ("pre_filter", "post_filter"):
        found = search(
            store,
            config,
            query="near",
            owner_id=owner_id,
            node_types=["Fact"],
            similarity_threshold=0.55,
            search_type=search_type,
        )
        assert found["success"], found
        texts = [row["text"] for row in found["results"]]
        assert texts == ["near", "mid", "side"]
        scores = [row["similarity"] for row in found["results"]]
        assert scores[0] == pytest.approx(1.0, abs=1e-5)
        assert scores[1] == pytest.approx(0.8, abs=1e-4)
        assert scores[2] == pytest.approx(0.6, abs=1e-4)
        assert store.last_vector_search["filtered"] is True
        assert store.last_vector_search["ef_search"] >= 500

    unfiltered = search(
        store,
        config,
        query="near",
        owner_id=owner_id,
        node_types=["Fact"],
        similarity_threshold=0.0,
        include_outdated=True,
        search_type="pre_filter",
    )
    assert [row["text"] for row in unfiltered["results"]] == ["near", "mid", "side", "far"]
    assert store.last_vector_search["filtered"] is False
    assert store.last_vector_search["ef_search"] is None


def test_metadata_filter_and_outdated(store):
    config = _config()
    owner_id = _owner()
    kept = _create(store, config, owner_id, "near", metadata={"project": "alpha"})
    _create(store, config, owner_id, "near", metadata={"project": "beta"})
    found = search(
        store,
        config,
        query="near",
        owner_id=owner_id,
        node_types=["Fact"],
        metadata_filter={"project": "alpha"},
        similarity_threshold=0.55,
    )
    assert [row["node_id"] for row in found["results"]] == [kept["node_id"]]
    assert store.last_vector_search["filtered"] is True
    assert store.last_vector_search["rid_count"] == 1
    assert store.last_vector_search["ef_search"] >= 500

    update_node(store, node_id=kept["node_id"], owner_id=owner_id, status="outdated")
    hidden = search(
        store, config, query="near", owner_id=owner_id, similarity_threshold=0.55
    )
    assert kept["node_id"] not in [row["node_id"] for row in hidden["results"]]
    shown = search(
        store,
        config,
        query="near",
        owner_id=owner_id,
        similarity_threshold=0.55,
        include_outdated=True,
        metadata_filter={"project": "alpha"},
    )
    assert kept["node_id"] in [row["node_id"] for row in shown["results"]]


def test_owner_isolation_and_delete(store):
    config = _config()
    alpha = _owner()
    beta = _owner()
    own = _create(store, config, alpha, "near")
    other = _create(store, config, beta, "near")
    found = search(
        store, config, query="near", owner_id=alpha, similarity_threshold=0.55
    )
    ids = [row["node_id"] for row in found["results"]]
    assert own["node_id"] in ids
    assert other["node_id"] not in ids
    assert store.database_name(alpha) == f"{_DATABASE}_{alpha}"
    assert store.database_name(beta) == f"{_DATABASE}_{beta}"
    assert store.database_name(alpha) != store.database_name(beta)
    assert store.get_vector_index_status(alpha)["Fact"] is True
    assert store.get_vector_index_status(beta)["Fact"] is True
    with store.owner_scope(beta):
        leaked = store.query(
            "SELECT uid FROM Fact WHERE uid = :uid", {"uid": own["node_id"]}
        )
    assert leaked == []
    with store.owner_scope(alpha):
        foreign = store.query(
            "SELECT uid FROM Fact WHERE uid = :uid", {"uid": other["node_id"]}
        )
    assert foreign == []
    assert store.delete_owner_graph(beta) is True
    assert beta not in store.list_owners()
    assert store.database_name(beta) not in store.list_database_names()
    assert alpha in store.list_owners()
    assert get_node(store, node_id=other["node_id"], owner_id=beta)["code"] == "memory_not_found"


def test_default_owner_has_its_own_database(store):
    config = _config()
    node = _create(store, config, "default", "near")
    assert store.database_name("default") == f"{_DATABASE}_default"
    assert "default" in store.list_owners()
    fetched = get_node(store, node_id=node["node_id"], owner_id="default")
    assert fetched["success"]
    assert fetched["node"]["text"] == "near"
    assert store.get_vector_index_status("default")["Fact"] is True


def test_find_similar_excludes_seed(store):
    config = _config()
    owner_id = _owner()
    seed = _create(store, config, owner_id, "near")
    other = _create(store, config, owner_id, "mid")
    _create(store, config, owner_id, "far")
    found = find_similar(
        store, config, fact_id=seed["node_id"], owner_id=owner_id, similarity_threshold=0.55
    )
    ids = [row["node_id"] for row in found["similar_facts"]]
    assert ids == [other["node_id"]]
    assert found["similar_facts"][0]["similarity"] == pytest.approx(0.8, abs=1e-4)


def test_relations_context_trace_unlink(store):
    config = _config()
    owner_id = _owner()
    left = _create(store, config, owner_id, "near")
    right = _create(store, config, owner_id, "far")
    linked = create_relation(
        store,
        from_id=left["node_id"],
        to_id=right["node_id"],
        relation_type="RELATED_TO",
        properties={"strength": 2},
        owner_id=owner_id,
        config=config,
    )
    assert linked["success"], linked
    assert linked["relation_type"] == "RELATED_TO"

    traced = get_trace(
        store, from_id=left["node_id"], to_id=right["node_id"], owner_id=owner_id
    )
    assert [node["node_id"] for node in traced["nodes"]] == [left["node_id"], right["node_id"]]
    assert traced["relations"][0]["relation_type"] == "RELATED_TO"

    # Changing text rewrites the vertex so the new embedding stays in the HNSW.
    rewritten = update_node(
        store, node_id=left["node_id"], owner_id=owner_id, text="mid"
    )
    assert rewritten["success"], rewritten
    still = get_trace(
        store, from_id=left["node_id"], to_id=right["node_id"], owner_id=owner_id
    )
    assert [node["node_id"] for node in still["nodes"]] == [left["node_id"], right["node_id"]]

    context = get_context(store, config, node_id=left["node_id"], owner_id=owner_id, depth=1)
    assert right["node_id"] in [node["node_id"] for node in context["nodes"]]
    assert context["edges"][0]["properties"]["strength"] == 2

    removed = unlink_facts(
        store,
        from_id=left["node_id"],
        to_id=right["node_id"],
        relation_type="RELATED_TO",
        owner_id=owner_id,
    )
    assert removed["deleted"] == 1
    empty = get_trace(
        store, from_id=left["node_id"], to_id=right["node_id"], owner_id=owner_id
    )
    assert empty["nodes"] == []


def test_version_history_as_of(store):
    config = _config()
    owner_id = _owner()
    node = _create(store, config, owner_id, "near")
    time.sleep(0.02)
    updated = update_node(
        store,
        node_id=node["node_id"],
        owner_id=owner_id,
        text="mid",
        versioning=True,
    )
    assert updated["node"]["text"] == "mid"
    previous = get_node(
        store, node_id=node["node_id"], owner_id=owner_id, as_of=node["created_at"]
    )
    assert previous["success"], previous
    assert previous["node"]["text"] == "near"


def test_export_import_roundtrip(store):
    config = _config()
    source = _owner()
    target = _owner()
    left = _create(store, config, source, "near")
    right = _create(store, config, source, "mid")
    assert create_relation(
        store,
        from_id=left["node_id"],
        to_id=right["node_id"],
        relation_type="RELATED_TO",
        owner_id=source,
        config=config,
    )["success"]
    payload = export_owner(store, owner_id=source, include_embeddings=True)
    assert payload["node_count"] == 2
    assert payload["relation_count"] == 1
    assert len(payload["nodes"][0]["properties"]["embedding"]) == 4

    imported = import_owner(
        store,
        owner_id=target,
        nodes=payload["nodes"],
        relations=payload["relations"],
    )
    assert imported["imported_nodes"] == 2
    assert imported["imported_relations"] == 1
    copied = get_node(store, node_id=left["node_id"], owner_id=target)
    assert copied["node"]["text"] == "near"
    traced = get_trace(
        store, from_id=left["node_id"], to_id=right["node_id"], owner_id=target
    )
    assert len(traced["nodes"]) == 2


def test_error_paths(store):
    config = _config()
    owner_id = _owner()
    bad_owner = create_node(
        store, config, text="near", owner_id="bad owner", auto_link=False
    )
    assert bad_owner["code"] == "memory_validation_error"

    bad_search = search(store, config, query="near", owner_id=owner_id, search_type="nope")
    assert bad_search["code"] == "memory_validation_error"

    strict = _config(relation_policy_enforce="enforce", relation_allowed_types="RELATED_TO")
    left = _create(store, config, owner_id, "near")
    right = _create(store, config, owner_id, "far")
    denied = create_relation(
        store,
        from_id=left["node_id"],
        to_id=right["node_id"],
        relation_type="NOT_A_REAL_EDGE",
        owner_id=owner_id,
        config=strict,
    )
    assert denied["code"] == "memory_relation_policy_error"

    missing = delete_node(store, node_id="a" * 32, owner_id=owner_id)
    assert missing["code"] == "memory_not_found"

    store.set_embedding_service(_Wide())
    try:
        mismatch = create_node(
            store, config, text="other", owner_id=owner_id, auto_link=False
        )
        assert mismatch["code"] == "memory_validation_error"
    finally:
        store.set_embedding_service(_Vectors())


def test_health_reports_arcade_without_dropping_falkor_key(store):
    store.ensure_search_indexes_if_missing(dimension=4)
    payload = health_check(store, store._embedding_service)
    assert payload["falkordb"] is False
    assert payload["embeddings"] is True
    assert payload["vector_index"] is True
    assert payload["healthy"] is True
    assert store.get_vector_index_status() == {"Fact": True, "Entity": True}
