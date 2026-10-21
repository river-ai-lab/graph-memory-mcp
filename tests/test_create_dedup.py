"""create_node duplicate gate and long-text warning. Live case runs on both stores."""

from __future__ import annotations

import uuid

import pytest

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import (
    _blocking_duplicates,
    _long_text_warnings,
    create_node,
)


def test_high_similarity_blocks_without_an_identifier_list():
    cfg = load_mcp_server_config()
    near = [
        {
            "node_id": "old",
            "text": "rerun head 16 with 24Gi after failures",
            "similarity": 0.96,
        }
    ]
    blocked = _blocking_duplicates(cfg, "rerun head 16 with 48Gi after failures", near)
    assert blocked[0]["node_id"] == "old"
    assert "48gi" in blocked[0]["diff_hint"]


def test_paraphrase_without_new_identifier_blocks():
    cfg = load_mcp_server_config()
    near = [
        {
            "node_id": "old",
            "text": "union theta is frozen for 1990-2020",
            "similarity": 0.95,
        }
    ]
    blocked = _blocking_duplicates(cfg, "union theta stays frozen for 1990-2020", near)
    assert blocked[0]["node_id"] == "old"
    assert "diff_hint" in blocked[0]


def test_long_text_warns_without_being_a_limit():
    cfg = load_mcp_server_config()
    assert _long_text_warnings(cfg, "short fact") == []
    warnings = _long_text_warnings(cfg, "x" * 700)
    assert warnings
    assert "not blocked" in warnings[0]


@pytest.mark.integration
def test_create_node_blocks_paraphrase_until_check_is_disabled(memory_backend):
    cfg = memory_backend.config
    db = memory_backend.db
    owner_id = f"pytest_dedup_{uuid.uuid4().hex[:8]}"
    text = "Claim year forecast uses frozen union theta from 1990 to 2020"

    first = create_node(db, cfg, text=text, owner_id=owner_id, auto_link=False)
    assert first["success"] is True

    blocked = create_node(
        db,
        cfg,
        text=text,
        owner_id=owner_id,
        auto_link=False,
    )
    assert blocked["success"] is False
    assert blocked["code"] == "memory_duplicate"
    assert blocked["possible_duplicates"]

    forced = create_node(
        db,
        cfg,
        text=text,
        owner_id=owner_id,
        auto_link=False,
        check_duplicates=False,
    )
    assert forced["success"] is True

    long_text = "durable note " + ("detail " * 120)
    warned = create_node(db, cfg, text=long_text, owner_id=owner_id, auto_link=False)
    assert warned["success"] is True
    assert warned["warnings"]
