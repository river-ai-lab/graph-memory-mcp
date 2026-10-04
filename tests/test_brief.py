"""get_brief snapshot and search contradiction pairs. Needs FalkorDB."""

from __future__ import annotations

import uuid

import pytest

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService
from graph_memory_mcp.graph_memory.mcp_handlers_admin import get_brief
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import create_node, upsert_node
from graph_memory_mcp.graph_memory.mcp_handlers_relations import create_relation
from graph_memory_mcp.graph_memory.mcp_handlers_search import search


def _db():
    cfg = load_mcp_server_config()
    db = FalkorDBClient(cfg)
    if not db.connect():
        pytest.fail("FalkorDB connection failed")
    db.set_embedding_service(EmbeddingService(model_name=cfg.embedding_model))
    return cfg, db


@pytest.mark.integration
def test_get_brief_anchor_recency_and_ttl():
    """Brief is about + recent facts, not a degree ranking, and skips TTL nodes."""
    cfg, db = _db()
    owner_id = f"pytest_brief_{uuid.uuid4().hex[:8]}"

    empty = get_brief(db, owner_id=owner_id)
    assert empty["success"] is True
    assert empty["about"] is None

    hub = create_node(
        db,
        cfg,
        text="old hub fact that should not lead just because it has many links",
        owner_id=owner_id,
        auto_link=False,
    )
    hub_id = hub["node"]["node_id"]
    for i in range(3):
        mention = create_node(
            db,
            cfg,
            text=f"mention target {i}",
            node_type="Entity",
            owner_id=owner_id,
            auto_link=False,
        )
        create_relation(
            db,
            from_id=hub_id,
            to_id=mention["node"]["node_id"],
            relation_type="MENTIONS",
            owner_id=owner_id,
            config=cfg,
        )

    recent = create_node(
        db,
        cfg,
        text="newest durable fact about the current state",
        owner_id=owner_id,
        auto_link=False,
    )
    recent_id = recent["node"]["node_id"]
    create_relation(
        db,
        from_id=hub_id,
        to_id=recent_id,
        relation_type="CONTRADICTS",
        owner_id=owner_id,
        config=cfg,
    )

    temporary = create_node(
        db,
        cfg,
        text="pod left running on 24Gi",
        owner_id=owner_id,
        ttl_days=7,
        auto_link=False,
    )
    temporary_id = temporary["node"]["node_id"]
    create_relation(
        db,
        from_id=temporary_id,
        to_id=recent_id,
        relation_type="CONTRADICTS",
        owner_id=owner_id,
        config=cfg,
    )

    about = upsert_node(
        db,
        cfg,
        text="This project tracks wheat yield models.",
        owner_id=owner_id,
        source={"ref": "about"},
        auto_link=False,
    )
    assert about["success"] is True

    brief = get_brief(db, owner_id=owner_id, limit=10)
    assert brief["about"]["text"] == "This project tracks wheat yield models."
    assert brief["about"]["source_ref"] == "about"

    ids = [fact["node_id"] for fact in brief["top_facts"]]
    assert recent_id in ids
    assert hub_id in ids
    assert temporary_id not in ids
    assert ids.index(recent_id) < ids.index(hub_id)
    assert all("degree" not in fact for fact in brief["top_facts"])

    pairs = {(row["from_id"], row["to_id"]) for row in brief["contradictions"]}
    assert (hub_id, recent_id) in pairs or (recent_id, hub_id) in pairs
    assert all(temporary_id not in pair for pair in pairs)


@pytest.mark.integration
def test_search_returns_existing_contradiction_pair():
    cfg, db = _db()
    owner_id = f"pytest_contra_{uuid.uuid4().hex[:8]}"
    left = create_node(
        db,
        cfg,
        text="claim year uses USDA Emerged and Headed inside the window",
        owner_id=owner_id,
        auto_link=False,
    )
    right = create_node(
        db,
        cfg,
        text="claim year has no USDA Emerged or Headed stages in the window",
        owner_id=owner_id,
        auto_link=False,
        check_duplicates=False,
    )
    create_relation(
        db,
        from_id=left["node"]["node_id"],
        to_id=right["node"]["node_id"],
        relation_type="CONTRADICTS",
        owner_id=owner_id,
        config=cfg,
    )

    found = search(
        db,
        cfg,
        query="USDA Emerged Headed claim year window",
        owner_id=owner_id,
        limit=5,
    )
    assert found["success"] is True
    hit_ids = {row["node_id"] for row in found["results"]}
    assert left["node"]["node_id"] in hit_ids
    assert right["node"]["node_id"] in hit_ids
    assert any(
        {pair["from_id"], pair["to_id"]}
        == {left["node"]["node_id"], right["node"]["node_id"]}
        and pair["relation_type"] == "CONTRADICTS"
        for pair in found["contradiction_pairs"]
    )
    assert "get_trace" in found["suggested_next"][0]
    assert "mark_outdated" in found["suggested_next"][1]
