"""Tests for ingest_knowledge, export pagination, batch import, versioning default."""

from __future__ import annotations

import uuid

import pytest

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory import mcp_handlers_admin as admin
from graph_memory_mcp.graph_memory import mcp_handlers_graph as graph_mod
from graph_memory_mcp.graph_memory import mcp_handlers_nodes as nodes
from graph_memory_mcp.graph_memory import mcp_handlers_relations as rel  # noqa: F401
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService
from graph_memory_mcp.graph_memory.mcp_handlers_ingest import ingest_knowledge


@pytest.fixture(scope="module")
def db_client():
    cfg = load_mcp_server_config()
    db = FalkorDBClient(cfg)
    if not db.connect():
        pytest.fail("FalkorDB connection failed")
    db.set_embedding_service(EmbeddingService(model_name=cfg.embedding_model))
    return db


def _doc_payload(ref: str) -> dict:
    return {
        "document": {"ref": ref, "title": "Planning meeting", "type": "conversation"},
        "facts": [
            {
                "text": "Client X migrates to PostgreSQL in Q3",
                "metadata": {"tags": ["decision"]},
            },
            {"text": "Budget for migration is approved"},
        ],
        "triplets": [
            {"subject": "Client X", "predicate": "USES", "object": "PostgreSQL"},
        ],
    }


@pytest.mark.integration
def test_ingest_knowledge_full_flow(db_client):
    cfg = load_mcp_server_config()
    owner = f"pytest_ingest_{uuid.uuid4().hex[:8]}"
    doc_ref = f"meeting-{uuid.uuid4().hex[:8]}"

    result = ingest_knowledge(db_client, cfg, owner_id=owner, **_doc_payload(doc_ref))
    assert result["success"] is True
    assert result["document_operation"] == "created"
    assert result["fact_count"] == 2
    assert result["triplet_count"] == 1
    document_id = result["document_id"]

    # Facts carry provenance refs and are linked EXTRACTED_FROM -> document.
    fact_ids = [f["node_id"] for f in result["facts"]]
    assert result["facts"][0]["ref"] == f"{doc_ref}#0"
    context = graph_mod.get_context(
        db_client, cfg, node_id=document_id, owner_id=owner, depth=1, max_nodes=20
    )
    extracted = [e for e in context["edges"] if e["relation_type"] == "EXTRACTED_FROM"]
    assert {e["from_id"] for e in extracted} == set(fact_ids)

    # Triplet entities exist and are searchable.
    triplets = rel.search_triplets(db_client, subject="Client X", owner_id=owner)
    assert len(triplets["triplets"]) == 1


@pytest.mark.integration
def test_ingest_knowledge_idempotent_and_updates(db_client):
    cfg = load_mcp_server_config()
    owner = f"pytest_ingest_re_{uuid.uuid4().hex[:8]}"
    doc_ref = f"doc-{uuid.uuid4().hex[:8]}"

    first = ingest_knowledge(db_client, cfg, owner_id=owner, **_doc_payload(doc_ref))
    payload = _doc_payload(doc_ref)
    payload["facts"][0]["text"] = "Client X migrates to PostgreSQL in Q4"  # edited
    second = ingest_knowledge(db_client, cfg, owner_id=owner, **payload)

    assert second["success"] is True
    assert second["document_operation"] == "updated"
    # Same uids — updated in place, not duplicated.
    assert [f["node_id"] for f in first["facts"]] == [
        f["node_id"] for f in second["facts"]
    ]
    assert all(f["operation"] == "updated" for f in second["facts"])

    updated = nodes.get_node(
        db_client, node_id=first["facts"][0]["node_id"], owner_id=owner
    )
    assert "Q4" in updated["node"]["text"]

    stats = admin.get_stats(db_client, owner_id=owner)
    # 1 document + 2 facts + 2 triplet entities = 5 (no duplicates from re-ingest)
    assert stats["stats"]["total_nodes"] == 5


def test_ingest_knowledge_validation(db_client):
    cfg = load_mcp_server_config()
    no_ref = ingest_knowledge(
        db_client, cfg, document={}, facts=[{"text": "x"}], owner_id="default"
    )
    assert no_ref["code"] == "memory_validation_error"

    empty = ingest_knowledge(
        db_client, cfg, document={"ref": "d"}, facts=[], triplets=[], owner_id="default"
    )
    assert empty["code"] == "memory_validation_error"

    bad_fact = ingest_knowledge(
        db_client, cfg, document={"ref": "d"}, facts=[{"nope": 1}], owner_id="default"
    )
    assert bad_fact["code"] == "memory_validation_error"

    bad_triplet = ingest_knowledge(
        db_client,
        cfg,
        document={"ref": "d"},
        triplets=[{"subject": "a"}],
        owner_id="default",
    )
    assert bad_triplet["code"] == "memory_validation_error"


@pytest.mark.integration
def test_export_pagination_covers_full_dataset(db_client):
    cfg = load_mcp_server_config()
    owner = f"pytest_page_{uuid.uuid4().hex[:8]}"
    created = nodes.create_nodes(
        db_client,
        cfg,
        items=[{"text": f"page fact {i}"} for i in range(5)],
        owner_id=owner,
    )
    ids = [n["node_id"] for n in created["nodes"]]
    rel.create_relation(
        db_client,
        from_id=ids[0],
        to_id=ids[1],
        relation_type="RELATED_TO",
        owner_id=owner,
        config=cfg,
    )

    # Page nodes with limit=2 until has_more is false.
    collected = []
    offset = 0
    while True:
        page = admin.export_owner(
            db_client, owner_id=owner, limit=2, offset=offset, section="nodes"
        )
        assert page["success"] and page["section"] == "nodes"
        collected.extend(page["nodes"])
        if not page["has_more"]:
            break
        offset = page["next_offset"]
    assert {n["properties"]["uid"] for n in collected} == set(ids)

    rel_page = admin.export_owner(
        db_client, owner_id=owner, limit=10, section="relations"
    )
    assert rel_page["relation_count"] == 1

    full = admin.export_owner(db_client, owner_id=owner)
    assert full["node_count"] == 5 and full["relation_count"] == 1
    assert "has_more" not in full

    bad = admin.export_owner(db_client, owner_id=owner, section="bogus")
    assert bad["code"] == "memory_validation_error"


@pytest.mark.integration
def test_batch_import_roundtrip(db_client):
    cfg = load_mcp_server_config()
    src = f"pytest_bimp_{uuid.uuid4().hex[:8]}"
    dst = f"{src}_copy"

    created = nodes.create_nodes(
        db_client,
        cfg,
        items=[{"text": f"batch import fact {i}"} for i in range(7)],
        owner_id=src,
    )
    ids = [n["node_id"] for n in created["nodes"]]
    for a, b in zip(ids, ids[1:]):
        rel.create_relation(
            db_client,
            from_id=a,
            to_id=b,
            relation_type="FOLLOWS_FROM",
            owner_id=src,
            config=cfg,
        )

    exported = admin.export_owner(db_client, owner_id=src)
    imported = admin.import_owner(
        db_client,
        owner_id=dst,
        nodes=exported["nodes"],
        relations=exported["relations"],
    )
    assert imported["imported_nodes"] == 7
    assert imported["imported_relations"] == 6

    stats = admin.get_stats(db_client, owner_id=dst)
    assert stats["stats"]["total_nodes"] == 7
    assert stats["stats"]["total_relations"] == 6

    # Idempotent re-import.
    admin.import_owner(
        db_client,
        owner_id=dst,
        nodes=exported["nodes"],
        relations=exported["relations"],
    )
    stats2 = admin.get_stats(db_client, owner_id=dst)
    assert stats2["stats"]["total_nodes"] == 7
    assert stats2["stats"]["total_relations"] == 6


@pytest.mark.integration
def test_bfs_context_hub_budget(db_client):
    """Hub with many neighbors: BFS returns within budget, no path explosion."""
    cfg = load_mcp_server_config()
    owner = f"pytest_hub_{uuid.uuid4().hex[:8]}"

    hub = nodes.create_node(
        db_client, cfg, text="hub fact", owner_id=owner, auto_link=False
    )["node"]["node_id"]
    created = nodes.create_nodes(
        db_client,
        cfg,
        items=[{"text": f"spoke {i}"} for i in range(15)],
        owner_id=owner,
    )
    for spoke in created["nodes"]:
        rel.create_relation(
            db_client,
            from_id=hub,
            to_id=spoke["node_id"],
            relation_type="RELATED_TO",
            owner_id=owner,
            config=cfg,
        )

    result = graph_mod.get_context(
        db_client, cfg, node_id=hub, owner_id=owner, depth=2, max_nodes=6
    )
    assert result["success"] is True
    assert len(result["nodes"]) == 6  # hub + 5 neighbors, budget respected
    assert any(n["node_id"] == hub for n in result["nodes"])

    # Chain reachability: BFS still walks depth correctly.
    a, b = created["nodes"][0]["node_id"], created["nodes"][1]["node_id"]
    two_hops = graph_mod.get_context(
        db_client, cfg, node_id=a, owner_id=owner, depth=2, max_nodes=50
    )
    ids = {n["node_id"] for n in two_hops["nodes"]}
    assert hub in ids and b in ids  # a -> hub (1 hop) -> b (2 hops)


@pytest.mark.integration
def test_archive_stale_facts_flag(db_client, monkeypatch):
    """With JOB_ARCHIVE_STALE_ENABLED, facts unused for stale_facts_days archive."""
    import asyncio
    import time as time_mod

    from graph_memory_mcp.jobs.archive_old_facts import archive_old_facts

    owner = f"pytest_stalearc_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("JOBS_ENABLED", "true")
    monkeypatch.setenv("JOB_ARCHIVE_ENABLED", "true")
    monkeypatch.setenv("JOB_ARCHIVE_STALE_ENABLED", "true")
    monkeypatch.setenv("JOBS_OWNER_IDS", owner)
    cfg = load_mcp_server_config()

    stale = nodes.create_node(
        db_client, cfg, text="stale unused fact", owner_id=owner, auto_link=False
    )["node"]["node_id"]
    fresh = nodes.create_node(
        db_client, cfg, text="fresh fact", owner_id=owner, auto_link=False
    )["node"]["node_id"]

    old_ms = int(time_mod.time() * 1000) - 60 * 24 * 3600 * 1000  # 60 days ago
    db_client.query(
        "MATCH (f:Fact) WHERE f.uid = $u SET f.created_at = $t",
        params={"u": stale, "t": old_ms, "owner_id": owner},
    )

    asyncio.run(archive_old_facts(db=db_client, config=cfg))

    assert (
        nodes.get_node(db_client, node_id=stale, owner_id=owner)["node"]["status"]
        == "archived"
    )
    assert (
        nodes.get_node(db_client, node_id=fresh, owner_id=owner)["node"]["status"]
        == "active"
    )


@pytest.mark.integration
def test_owner_graph_delete_and_prune(db_client):
    cfg = load_mcp_server_config()
    live = f"pytest_live_{uuid.uuid4().hex[:8]}"
    empty = f"pytest_empty_{uuid.uuid4().hex[:8]}"

    nodes.create_node(db_client, cfg, text="keep me", owner_id=live, auto_link=False)
    doomed = nodes.create_node(
        db_client, cfg, text="delete me", owner_id=empty, auto_link=False
    )["node"]["node_id"]
    nodes.delete_node(db_client, node_id=doomed, owner_id=empty)

    assert {live, empty} <= set(db_client.list_owners())

    pruned = db_client.prune_empty_owner_graphs()
    owners_after = set(db_client.list_owners())
    assert empty in pruned and empty not in owners_after
    assert live in owners_after

    assert db_client.delete_owner_graph(live) is True
    assert live not in set(db_client.list_owners())


@pytest.mark.integration
def test_admin_owner_routes(db_client):
    from starlette.testclient import TestClient

    from graph_memory_mcp.server import GraphMemoryMCP

    cfg = load_mcp_server_config()
    owner = f"pytest_admin_del_{uuid.uuid4().hex[:8]}"
    nodes.create_node(
        db_client, cfg, text="to be deleted", owner_id=owner, auto_link=False
    )

    server = GraphMemoryMCP(cfg)
    app = server.get_mcp_app()
    with TestClient(app) as client:
        gone = client.delete(f"/admin/owners/{owner}")
        assert gone.status_code == 200 and gone.json()["success"] is True

        missing = client.delete(f"/admin/owners/{owner}")
        assert missing.status_code == 404

        pruned = client.post("/admin/prune-empty-owners")
        assert pruned.json()["success"] is True


@pytest.mark.integration
def test_versioning_default_config(db_client, monkeypatch):
    owner = f"pytest_vdef_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("VERSIONING_DEFAULT", "true")
    cfg = load_mcp_server_config()
    db = FalkorDBClient(cfg)
    db.set_embedding_service(db_client._embedding_service)

    created = nodes.create_node(
        db, cfg, text="versioned by default", owner_id=owner, auto_link=False
    )
    node_id = created["node"]["node_id"]
    # No explicit versioning flag — config default applies.
    nodes.update_node(db, node_id=node_id, owner_id=owner, text="edited")

    history = nodes.get_node_change_history(db, node_id=node_id, owner_id=owner)
    assert history["count"] >= 1
    assert history["versions"][0]["text"] == "versioned by default"
