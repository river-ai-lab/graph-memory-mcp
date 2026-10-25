"""Vector indexes: a missing one stays healthy, and the first write creates both."""

from __future__ import annotations

import uuid

from graph_memory_mcp.graph_memory.mcp_handlers_admin import health_check
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import create_node
from graph_memory_mcp.graph_memory.mcp_handlers_search import search


def _drop_vector_indexes(db, owner_id: str) -> None:
    """Remove Fact and Entity vector indexes without deleting the graph."""
    status = db.get_vector_index_status(owner_id)
    if hasattr(db, "graph_for"):
        graph = db.graph_for(owner_id)
        for label, present in status.items():
            if not present:
                continue
            graph.query(f"DROP VECTOR INDEX FOR (n:{label}) ON (n.embedding)")
        ready = getattr(db, "_search_indexes_ready", None)
        if isinstance(ready, set):
            ready.discard(db.graph_name(owner_id))
        _discard_vector_cache(db, owner_id)
        return
    _discard_vector_cache(db, owner_id)
    with db.owner_scope(owner_id):
        for label, present in status.items():
            if not present:
                continue
            db.command(f"DROP INDEX `{label}[embedding]`")


def _discard_vector_cache(db, owner_id: str) -> None:
    ready = getattr(db, "_vector_indexes_ready", None)
    if not isinstance(ready, set):
        return
    key = (
        db.graph_name(owner_id)
        if hasattr(db, "graph_for")
        else db.database_name(owner_id)
    )
    ready.discard(key)


def _index_cache_key(db, owner_id: str) -> str:
    if hasattr(db, "graph_for"):
        return db.graph_name(owner_id)
    return db.database_name(owner_id)


def test_create_node_creates_vector_indexes_before_search(memory_backend):
    """A fresh owner's first create_node creates Fact and Entity indexes, with no search."""
    cfg = memory_backend.config
    db = memory_backend.db
    owner_id = f"0idxnow_{uuid.uuid4().hex[:8]}"
    text = f"First write creates vector indexes {owner_id}"
    try:
        before = db.get_vector_index_status(owner_id)
        assert before == {"Fact": False, "Entity": False}

        created = create_node(
            db,
            cfg,
            text=text,
            node_type="Fact",
            owner_id=owner_id,
            check_duplicates=False,
            auto_link=False,
        )
        assert created.get("success") is True, created

        status = db.get_vector_index_status(owner_id)
        assert status == {"Fact": True, "Entity": True}
        assert _index_cache_key(db, owner_id) in db._vector_indexes_ready

        payload = health_check(db, db._embedding_service)
        assert payload["success"] is True
        assert payload["healthy"] is True
        assert owner_id not in payload["vector_index_missing"]
    finally:
        db.delete_owner_graph(owner_id)


def test_owner_without_vector_index_stays_healthy(memory_backend):
    """health_check reports the gap. The next search creates the index and finds the fact."""
    cfg = memory_backend.config
    db = memory_backend.db
    owner_id = f"0idxgap_{uuid.uuid4().hex[:8]}"
    text = f"Fact stored before its vector index {owner_id}"
    try:
        created = create_node(
            db,
            cfg,
            text=text,
            node_type="Fact",
            owner_id=owner_id,
            check_duplicates=False,
            auto_link=False,
        )
        assert created.get("success") is True, created
        _drop_vector_indexes(db, owner_id)
        assert db.get_vector_index_status(owner_id)["Fact"] is False

        payload = health_check(db, db._embedding_service)
        assert payload["success"] is True
        assert payload["embeddings"] is True
        assert payload["healthy"] is True
        assert owner_id in payload["vector_index_missing"]
        assert payload["vector_index"] is False

        found = search(
            db,
            cfg,
            query=text,
            owner_id=owner_id,
            similarity_threshold=0.3,
            limit=5,
        )
        assert found.get("success") is True, found
        assert any(row.get("text") == text for row in found.get("results") or [])
        assert db.get_vector_index_status(owner_id)["Fact"] is True

        after = health_check(db, db._embedding_service)
        assert owner_id not in after["vector_index_missing"]
        assert after["healthy"] is True
    finally:
        db.delete_owner_graph(owner_id)
