"""get_context fills its node budget with explicit edges before MENTIONS."""

from __future__ import annotations

import uuid

import pytest

from graph_memory_mcp.graph_memory.mcp_handlers_graph import get_context
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import create_node
from graph_memory_mcp.graph_memory.mcp_handlers_relations import create_relation
from graph_memory_mcp.graph_memory.relation_policy import (
    DEFAULT_RELATION_ALLOWED_TYPES,
    neighbor_rank_expr,
)


def test_default_rank_puts_contradicts_before_mentions():
    expr = neighbor_rank_expr(None, frozenset(DEFAULT_RELATION_ALLOWED_TYPES))
    contradicts = expr.index("WHEN 'CONTRADICTS' THEN 0")
    follows = expr.index("WHEN 'FOLLOWS_FROM' THEN 1")
    mentions = expr.index("WHEN 'MENTIONS' THEN")
    assert contradicts < follows < mentions
    assert "WHEN 'RUNS_ON' THEN 2" in expr


def test_caller_priority_can_name_mentions():
    expr = neighbor_rank_expr(["MENTIONS", "CONTRADICTS"], frozenset())
    assert "WHEN 'MENTIONS' THEN 0" in expr
    assert "WHEN 'CONTRADICTS' THEN 1" in expr


@pytest.mark.integration
def test_context_budget_keeps_contradiction_ahead_of_mentions(memory_backend):
    cfg = memory_backend.config
    db = memory_backend.db
    owner_id = f"pytest_ctxpri_{uuid.uuid4().hex[:8]}"

    center = create_node(
        db,
        cfg,
        text="center fact for neighbor priority",
        owner_id=owner_id,
        auto_link=False,
        check_duplicates=False,
    )
    conflict = create_node(
        db,
        cfg,
        text="conflicting fact that must survive the budget",
        owner_id=owner_id,
        auto_link=False,
        check_duplicates=False,
    )
    assert center["success"] and conflict["success"]
    center_id = center["node"]["node_id"]
    conflict_id = conflict["node"]["node_id"]

    mentioned = []
    for index in range(8):
        entity = create_node(
            db,
            cfg,
            text=f"mentioned entity {index}",
            node_type="Entity",
            owner_id=owner_id,
            auto_link=False,
        )
        assert entity["success"]
        mentioned.append(entity["node"]["node_id"])
        linked = create_relation(
            db,
            from_id=center_id,
            to_id=entity["node"]["node_id"],
            relation_type="MENTIONS",
            owner_id=owner_id,
            config=cfg,
        )
        assert linked["success"]

    contradicted = create_relation(
        db,
        from_id=center_id,
        to_id=conflict_id,
        relation_type="CONTRADICTS",
        owner_id=owner_id,
        config=cfg,
    )
    assert contradicted["success"]

    found = get_context(
        db,
        cfg,
        node_id=center_id,
        owner_id=owner_id,
        depth=1,
        max_nodes=3,
    )
    assert found["success"] is True
    ids = {node["node_id"] for node in found["nodes"]}
    assert center_id in ids
    assert conflict_id in ids
    assert len(ids) <= 3

    hidden = get_context(
        db,
        cfg,
        node_id=center_id,
        owner_id=owner_id,
        depth=1,
        max_nodes=20,
        exclude_relation_types=["MENTIONS"],
    )
    hidden_ids = {node["node_id"] for node in hidden["nodes"]}
    assert conflict_id in hidden_ids
    assert mentioned[0] not in hidden_ids
