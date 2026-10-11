"""Default reads hide facts that have a TTL. Needs FalkorDB."""

from __future__ import annotations

import uuid

import pytest

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService
from graph_memory_mcp.graph_memory.mcp_handlers_admin import get_brief
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import create_node
from graph_memory_mcp.graph_memory.mcp_handlers_search import search


@pytest.mark.integration
def test_default_search_and_brief_hide_living_ttl_facts():
    cfg = load_mcp_server_config()
    db = FalkorDBClient(cfg)
    if not db.connect():
        pytest.fail("FalkorDB connection failed")
    db.set_embedding_service(EmbeddingService(model_name=cfg.embedding_model))
    owner_id = f"pytest_ttl_{uuid.uuid4().hex[:8]}"

    durable = create_node(
        db,
        cfg,
        text="Wheat protocol decision: keep the claim window at 1990-2020",
        owner_id=owner_id,
        auto_link=False,
    )
    temporary = create_node(
        db,
        cfg,
        text="Wheat protocol launch: pod started for the 1990-2020 window",
        owner_id=owner_id,
        ttl_days=14,
        auto_link=False,
        check_duplicates=False,
    )
    assert durable["success"] is True
    assert temporary["success"] is True
    durable_id = durable["node"]["node_id"]
    temporary_id = temporary["node"]["node_id"]

    hidden = search(
        db,
        cfg,
        query="Wheat protocol 1990-2020 window",
        owner_id=owner_id,
        similarity_threshold=0.0,
        node_types=["Fact"],
    )
    hidden_ids = {item["node_id"] for item in hidden["results"]}
    assert durable_id in hidden_ids
    assert temporary_id not in hidden_ids

    shown = search(
        db,
        cfg,
        query="Wheat protocol 1990-2020 window",
        owner_id=owner_id,
        similarity_threshold=0.0,
        node_types=["Fact"],
        include_ttl=True,
    )
    shown_ids = {item["node_id"] for item in shown["results"]}
    assert temporary_id in shown_ids

    brief = get_brief(db, owner_id=owner_id)
    brief_ids = {item["node_id"] for item in brief.get("top_facts") or []}
    assert temporary_id not in brief_ids
    assert durable_id in brief_ids
