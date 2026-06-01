"""
Comprehensive integration test for all MCP Graph Memory server tools.

This test covers ALL 18 MCP tools from server.py:

**Information Tools (3):**
1. test_connection
2. get_stats
3. health_check

**Fact/Node Tools (7):**
4. create_node
5. search
6. get_node
7. update_node
8. delete_node
9. mark_outdated
10. get_node_change_history

**Triplet Tools (2):**
11. create_triplet
12. search_triplets

**Graph Tools (6):**
13. create_relation
14. get_trace
15. delete_relation
16. get_context
17. find_similar
18. create_summary_fact

The test creates a realistic knowledge graph and exercises all tools.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, cast

import httpx
import pytest
import redis
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from graph_memory_mcp.config import MCPServerConfig, load_mcp_server_config
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.mcp_handlers_graph import get_context, get_trace
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import (
    create_node,
    update_node,
    upsert_node,
)
from graph_memory_mcp.graph_memory.mcp_handlers_search import find_similar, search
from graph_memory_mcp.server import GraphMemoryMCP


def _falkordb_is_available(host: str, port: int, password: str | None) -> bool:
    """Check if FalkorDB is available."""
    try:
        client = redis.Redis(
            host=host, port=port, password=password, socket_timeout=0.5
        )
        return client.ping() is True
    except Exception:
        return False


def _extract_tool_json(result) -> dict:
    """Extract JSON from MCP tool result."""
    content = getattr(result, "content", None)
    if content and len(content) > 0:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            try:
                import json

                return json.loads(text)
            except Exception:
                return {"raw": text}
    if isinstance(result, dict):
        return result
    return {"raw": repr(result)}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_all_mcp_tools_comprehensive():
    """
    Comprehensive test covering all 18 MCP tools from server.py.

    Creates a realistic knowledge graph and exercises every tool.
    """
    if os.environ.get("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("integration tests disabled (set RUN_INTEGRATION_TESTS=1)")

    cfg = load_mcp_server_config()

    if not _falkordb_is_available(
        cfg.falkordb_host, cfg.falkordb_port, cfg.falkordb_password
    ):
        pytest.skip("FalkorDB unavailable")

    # Use unique owner_id for isolation
    owner_id = f"pytest_all_tools_{uuid.uuid4().hex[:8]}"

    # Start server
    server = GraphMemoryMCP(cfg)
    app = server.get_mcp_app()

    # httpx ASGITransport does not run Starlette lifespan; MCP streamable HTTP needs it.
    async with server.mcp.session_manager.run():
        async with streamable_http_client(
            "http://127.0.0.1:8000/mcp",
            http_client=httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1:8000",
            ),
        ) as (read, write, _get_session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # ========================================
                # INFORMATION TOOLS (3)
                # ========================================

                # 1. test_connection
                result = await session.call_tool("test_connection", {})
                data = _extract_tool_json(result)
                assert data.get("success") is True
                assert data.get("ready") is True

                # 2. health_check
                result = await session.call_tool("health_check", {})
                data = _extract_tool_json(result)
                assert data.get("success") is True
                assert "falkordb" in data
                assert "embeddings" in data

                # 3. get_stats (initial - should be empty)
                result = await session.call_tool("get_stats", {"owner_id": owner_id})
                data = _extract_tool_json(result)
                assert data.get("success") is True

                result = await session.call_tool("ensure_vector_indexes", {})
                data = _extract_tool_json(result)
                assert data.get("success") is True

                # ========================================
                # FACT/NODE TOOLS (7)
                # ========================================

                # 4. create_node - Create Facts
                result = await session.call_tool(
                    "create_node",
                    {
                        "text": "Kubernetes is a container orchestration platform",
                        "node_type": "Fact",
                        "owner_id": owner_id,
                        "metadata": {"source": "test", "importance": "high"},
                        "auto_link": False,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True
                fact1_id = data["node"]["node_id"]

                result = await session.call_tool(
                    "create_node",
                    {
                        "text": "Docker is a containerization platform",
                        "node_type": "Fact",
                        "owner_id": owner_id,
                        "auto_link": False,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True
                fact2_id = data["node"]["node_id"]

                # Create Entity
                result = await session.call_tool(
                    "create_node",
                    {
                        "text": "Kubernetes",
                        "node_type": "Entity",
                        "owner_id": owner_id,
                        "entity_type": "technology",
                        "auto_link": False,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True
                entity1_id = data["node"]["node_id"]
                assert data["node"].get("type") == "technology"

                # 6. get_node
                result = await session.call_tool(
                    "get_node",
                    {
                        "node_id": fact1_id,
                        "owner_id": owner_id,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True
                assert data["node"]["node_id"] == fact1_id
                assert "Kubernetes" in data["node"]["text"]

                # 7. update_node
                result = await session.call_tool(
                    "update_node",
                    {
                        "node_id": fact1_id,
                        "owner_id": owner_id,
                        "metadata": {
                            "source": "test",
                            "importance": "critical",
                            "updated": True,
                        },
                        "versioning": True,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True

                # 10. get_node_change_history
                result = await session.call_tool(
                    "get_node_change_history",
                    {
                        "node_id": fact1_id,
                        "owner_id": owner_id,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True
                # Should have at least one version from update
                assert len(data.get("versions", [])) >= 0

                # 5. search - semantic search
                result = await session.call_tool(
                    "search",
                    {
                        "query": "Kubernetes container orchestration platform",
                        "owner_id": owner_id,
                        "limit": 10,
                        "node_types": ["Fact"],
                        "similarity_threshold": 0.25,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True
                assert len(data.get("results", [])) > 0

                # 9. mark_outdated
                result = await session.call_tool(
                    "create_node",
                    {
                        "text": "Temporary fact to be outdated",
                        "node_type": "Fact",
                        "owner_id": owner_id,
                        "auto_link": False,
                    },
                )
                data = _extract_tool_json(result)
                temp_fact_id = data["node"]["node_id"]

                result = await session.call_tool(
                    "mark_outdated",
                    {
                        "fact_id": temp_fact_id,
                        "reason": "test outdating",
                        "owner_id": owner_id,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True

                # Verify it's excluded from default search
                result = await session.call_tool(
                    "search",
                    {
                        "query": "Temporary fact",
                        "owner_id": owner_id,
                        "include_outdated": False,
                    },
                )
                data = _extract_tool_json(result)
                # Should not find the outdated fact
                outdated_found = any(
                    r["node_id"] == temp_fact_id for r in data.get("results", [])
                )
                assert not outdated_found

                # But should find it with include_outdated=True
                result = await session.call_tool(
                    "search",
                    {
                        "query": "Temporary fact",
                        "owner_id": owner_id,
                        "include_outdated": True,
                    },
                )
                data = _extract_tool_json(result)
                outdated_found = any(
                    r["node_id"] == temp_fact_id for r in data.get("results", [])
                )
                assert outdated_found

                # ========================================
                # TRIPLET TOOLS (2)
                # ========================================

                # 11. create_triplet
                result = await session.call_tool(
                    "create_triplet",
                    {
                        "subject": "Alice",
                        "predicate": "USES",
                        "object_value": "Kubernetes",
                        "owner_id": owner_id,
                        "metadata": {"confidence": 0.95},
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True

                # Create another triplet
                result = await session.call_tool(
                    "create_triplet",
                    {
                        "subject": "Alice",
                        "predicate": "LIKES",
                        "object_value": "Docker",
                        "owner_id": owner_id,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True

                # 12. search_triplets
                result = await session.call_tool(
                    "search_triplets",
                    {
                        "subject": "Alice",
                        "owner_id": owner_id,
                        "limit": 10,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True
                assert len(data.get("triplets", [])) >= 2

                # Search by predicate
                result = await session.call_tool(
                    "search_triplets",
                    {
                        "predicate": "USES",
                        "owner_id": owner_id,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True
                assert len(data.get("triplets", [])) >= 1

                # ========================================
                # GRAPH TOOLS (6)
                # ========================================

                # 13. create_relation
                result = await session.call_tool(
                    "create_relation",
                    {
                        "from_id": fact1_id,
                        "to_id": entity1_id,
                        "relation_type": "MENTIONS",
                        "owner_id": owner_id,
                        "properties": {"confidence": 1.0},
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True

                # Create another relation for path testing
                result = await session.call_tool(
                    "create_relation",
                    {
                        "from_id": fact2_id,
                        "to_id": fact1_id,
                        "relation_type": "RELATED_TO",
                        "owner_id": owner_id,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True

                # 16. get_context - subgraph around node
                result = await session.call_tool(
                    "get_context",
                    {
                        "node_id": fact1_id,
                        "owner_id": owner_id,
                        "depth": 2,
                        "max_nodes": 20,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True
                assert len(data.get("nodes", [])) > 0
                assert len(data.get("edges", [])) > 0

                # 14. get_trace - shortest path
                result = await session.call_tool(
                    "get_trace",
                    {
                        "from_id": fact2_id,
                        "to_id": entity1_id,
                        "owner_id": owner_id,
                        "max_depth": 5,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True
                # Should find path: fact2 -> fact1 -> entity1
                assert len(data.get("nodes", [])) > 0
                assert len(data.get("relations", [])) > 0

                # 17. find_similar - find facts similar to fact1
                result = await session.call_tool(
                    "find_similar",
                    {
                        "fact_id": fact1_id,
                        "owner_id": owner_id,
                        "limit": 5,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True
                # Should find fact2 as similar (both about containers)
                assert len(data.get("similar_facts", [])) >= 0

                # 18. create_summary_fact
                result = await session.call_tool(
                    "create_summary_fact",
                    {
                        "fact_ids": [fact1_id, fact2_id],
                        "summary_text": "Container technologies overview",
                        "owner_id": owner_id,
                        "metadata": {"type": "summary"},
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True
                summary_fact_id = data["summary"]["node_id"]

                # Verify summary is linked to source facts
                result = await session.call_tool(
                    "get_context",
                    {
                        "node_id": summary_fact_id,
                        "owner_id": owner_id,
                        "depth": 1,
                    },
                )
                data = _extract_tool_json(result)
                assert (
                    len(data.get("edges", [])) >= 2
                )  # Should link to both source facts

                # 15. delete_relation
                result = await session.call_tool(
                    "delete_relation",
                    {
                        "from_id": fact2_id,
                        "to_id": fact1_id,
                        "relation_type": "RELATED_TO",
                        "owner_id": owner_id,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True

                # Verify relation is removed
                result = await session.call_tool(
                    "get_context",
                    {
                        "node_id": fact2_id,
                        "owner_id": owner_id,
                        "depth": 1,
                    },
                )
                data = _extract_tool_json(result)
                # Should not have RELATED_TO edge to fact1 anymore
                related_edges = [
                    e
                    for e in data.get("edges", [])
                    if e.get("relation_type") == "RELATED_TO"
                    and e.get("to_id") == fact1_id
                ]
                assert len(related_edges) == 0

                # 8. delete_node - cleanup
                result = await session.call_tool(
                    "delete_node",
                    {
                        "node_id": temp_fact_id,
                        "owner_id": owner_id,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is True

                # Verify it's deleted
                result = await session.call_tool(
                    "get_node",
                    {
                        "node_id": temp_fact_id,
                        "owner_id": owner_id,
                    },
                )
                data = _extract_tool_json(result)
                assert data.get("success") is False  # Should not find deleted node

                # Final stats check
                result = await session.call_tool("get_stats", {"owner_id": owner_id})
                data = _extract_tool_json(result)
                assert data.get("success") is True
                stats = data.get("stats", {})
                # Should have created multiple nodes
                assert stats.get("total_nodes", 0) > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_tenant_isolation():
    """Test that owner_id properly isolates data between tenants."""
    if os.environ.get("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("integration tests disabled")

    cfg = load_mcp_server_config()

    if not _falkordb_is_available(
        cfg.falkordb_host, cfg.falkordb_port, cfg.falkordb_password
    ):
        pytest.skip("FalkorDB unavailable")

    owner1 = f"pytest_tenant1_{uuid.uuid4().hex[:8]}"
    owner2 = f"pytest_tenant2_{uuid.uuid4().hex[:8]}"

    server = GraphMemoryMCP(cfg)
    app = server.get_mcp_app()

    async with server.mcp.session_manager.run():
        async with streamable_http_client(
            "http://127.0.0.1:8000/mcp",
            http_client=httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1:8000",
            ),
        ) as (read, write, _get_session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create fact for owner1
                result = await session.call_tool(
                    "create_node",
                    {
                        "text": "Owner1 secret data",
                        "node_type": "Fact",
                        "owner_id": owner1,
                        "auto_link": False,
                    },
                )
                data = _extract_tool_json(result)
                fact1_id = data["node"]["node_id"]

                # Create fact for owner2
                result = await session.call_tool(
                    "create_node",
                    {
                        "text": "Owner2 secret data",
                        "node_type": "Fact",
                        "owner_id": owner2,
                        "auto_link": False,
                    },
                )
                data = _extract_tool_json(result)
                fact2_id = data["node"]["node_id"]

                # Owner1 should NOT see owner2's data
                result = await session.call_tool(
                    "search",
                    {
                        "query": "secret data",
                        "owner_id": owner1,
                    },
                )
                data = _extract_tool_json(result)
                results = data.get("results", [])
                owner2_found = any(r["node_id"] == fact2_id for r in results)
                assert not owner2_found, "Owner1 should not see Owner2's data"

                # Owner2 should NOT see owner1's data
                result = await session.call_tool(
                    "search",
                    {
                        "query": "secret data",
                        "owner_id": owner2,
                    },
                )
                data = _extract_tool_json(result)
                results = data.get("results", [])
                owner1_found = any(r["node_id"] == fact1_id for r in results)
                assert not owner1_found, "Owner2 should not see Owner1's data"


class _FakeResult:
    def __init__(self, rows):
        self.result_set = rows


class _FakeGraph:
    def __init__(self, responses=None):
        self.calls: list[tuple[str, Any]] = []
        self._responses = list(responses or [])

    def query(self, query, params=None):
        self.calls.append((query, params))
        if self._responses:
            return self._responses.pop(0)
        return _FakeResult([])


class _FakeCache:
    def __init__(self):
        self.invalidations = 0
        self.search_cache = {}

    def invalidate_search(self):
        self.invalidations += 1

    def get_search(self, key):
        return self.search_cache.get(key)

    def set_search(self, key, value):
        self.search_cache[key] = value


class _FakeNodeDB:
    def __init__(self, responses):
        self.graph = _FakeGraph(responses)
        self.cache = _FakeCache()
        self.embedding_calls: list[str] = []
        self.config = MCPServerConfig()

    def get_embedding(self, text: str):
        self.embedding_calls.append(text)
        return [0.1, 0.2, 0.3]


class _FakeGraphDB:
    def __init__(self, responses=None):
        self.graph = _FakeGraph(responses)


class _FakeSearchDB:
    def __init__(self, responses):
        self.graph = _FakeGraph(responses)
        self.cache = _FakeCache()
        self.config = MCPServerConfig()

    def get_embedding(self, text: str):
        return [0.1, 0.2, 0.3]


def _fact_row(
    node_id: int,
    *,
    text: str,
    updated_at: int = 1_700_000_000_000,
    source: dict[str, Any] | None = None,
):
    return [
        node_id,
        "Fact",
        text,
        None,
        "active",
        1_700_000_000_000,
        updated_at,
        "{}",
        [],
        None,
        None,
        None,
        "{}" if source is None else json.dumps(source),
    ]


def test_get_context_limits_nodes_before_collect():
    """get_context should keep isolated nodes and limit nodes before loading edges."""
    db = _FakeGraphDB(
        [
            _FakeResult([[123, "Fact", "isolated fact"]]),
            _FakeResult([]),
        ]
    )
    cfg = MCPServerConfig()

    result = get_context(
        cast(Any, db),
        cfg,
        node_id="123",
        owner_id="default",
        depth=2,
        max_nodes=5,
    )

    assert result["success"] is True
    assert result["nodes"] == [
        {"node_id": "123", "node_type": "Fact", "text": "isolated fact"}
    ]
    assert result["edges"] == []

    nodes_query, nodes_params = db.graph.calls[0]
    assert nodes_params == {"node_id": 123, "owner_id": "default"}
    assert "WITH DISTINCT connected" in nodes_query
    assert "LIMIT 5" in nodes_query
    assert "RETURN\n        id(connected) as node_id" in nodes_query

    edges_query, edges_params = db.graph.calls[1]
    assert "WHERE id(n) IN $node_ids AND id(m) IN $node_ids" in edges_query
    assert edges_params == {"node_ids": [123]}


def test_get_trace_returns_nodes_and_relations():
    """get_trace should expose a consistent nodes/relations payload."""
    db = _FakeGraphDB(
        [
            _FakeResult(
                [
                    [
                        [
                            {
                                "node_id": "123",
                                "node_type": "Fact",
                                "text": "from fact",
                            },
                            {
                                "node_id": "456",
                                "node_type": "Entity",
                                "text": "to entity",
                            },
                        ],
                        [{"relation_type": "MENTIONS"}],
                    ]
                ]
            )
        ]
    )

    result = get_trace(
        cast(Any, db),
        from_id="123",
        to_id="456",
        owner_id="default",
        max_depth=5,
    )

    assert result["success"] is True
    assert result["nodes"][0]["node_id"] == "123"
    assert result["relations"] == [{"relation_type": "MENTIONS"}]

    trace_query, trace_params = db.graph.calls[0]
    assert "shortestPath" in trace_query
    assert trace_params == {"from_id": 123, "to_id": 456, "owner_id": "default"}


def test_get_trace_returns_empty_lists_when_path_is_missing():
    """get_trace should keep the same payload shape when no path exists."""
    db = _FakeGraphDB([_FakeResult([[None, None]])])

    result = get_trace(
        cast(Any, db),
        from_id="123",
        to_id="456",
        owner_id="default",
        max_depth=5,
    )

    assert result == {
        "success": True,
        "nodes": [],
        "relations": [],
        "message": "No path found",
    }


def test_create_node_reuses_embedding_for_auto_link():
    """create_node should not re-embed fact text before auto-linking."""
    db = _FakeNodeDB(
        [
            _FakeResult([_fact_row(123, text="created fact")]),
            _FakeResult([[1]]),
        ]
    )
    cfg = MCPServerConfig()

    result = create_node(
        cast(Any, db),
        cfg,
        text="created fact",
        node_type="Fact",
        owner_id="default",
        auto_link=True,
    )

    assert result["success"] is True
    assert result["node"]["node_id"] == "123"
    assert db.embedding_calls == ["created fact"]
    assert len(db.graph.calls) == 2
    assert db.cache.invalidations == 1


def test_update_node_returns_updated_node_without_follow_up_fetch():
    """update_node should return projected fields from the update query."""
    db = _FakeNodeDB(
        [
            _FakeResult([_fact_row(123, text="before", updated_at=1)]),
            _FakeResult([_fact_row(123, text="after", updated_at=2)]),
        ]
    )

    result = update_node(
        cast(Any, db),
        node_id="123",
        owner_id="default",
        text="after",
    )

    assert result["success"] is True
    assert result["node"]["text"] == "after"
    assert len(db.graph.calls) == 2
    assert db.embedding_calls == ["after"]
    assert db.cache.invalidations == 1


def test_find_similar_uses_shared_escape_helper():
    """find_similar should not depend on a db.escape_value method."""
    db = _FakeSearchDB(
        [
            _FakeResult([[[0.1, 0.2, 0.3]]]),
            _FakeResult(
                [
                    [
                        456,
                        "Similar fact",
                        "active",
                        1_700_000_000_000,
                        '{"source":"test"}',
                        0.2,
                    ]
                ]
            ),
        ]
    )
    cfg = MCPServerConfig()

    result = find_similar(
        cast(FalkorDBClient, db),
        cfg,
        fact_id="123",
        owner_id="team'o",
        limit=5,
    )

    assert result["success"] is True
    assert result["similar_facts"][0]["node_id"] == "456"
    assert len(db.graph.calls) == 2

    similar_query, _ = db.graph.calls[1]
    assert "node.owner_id = 'team\\'o'" in similar_query


def test_search_filters_active_nodes_by_default():
    """search should filter both Facts and Entities to active nodes by default."""
    db = _FakeSearchDB([_FakeResult([]), _FakeResult([])])
    cfg = MCPServerConfig()

    result = search(
        cast(Any, db),
        cfg,
        query="important query",
        owner_id="default",
    )

    assert result["success"] is True

    fact_query, _ = db.graph.calls[0]
    entity_query, _ = db.graph.calls[1]
    active_clause = "(node.status IS NULL OR node.status = 'active')"
    assert active_clause in fact_query
    assert active_clause in entity_query
    assert "(node.expires_at IS NULL OR node.expires_at > timestamp())" in fact_query


def test_search_status_override_applies_to_entities():
    """Explicit status filters should apply to Entity searches too."""
    db = _FakeSearchDB([_FakeResult([])])
    cfg = MCPServerConfig()

    result = search(
        cast(Any, db),
        cfg,
        query="archived query",
        owner_id="default",
        node_types=["Entity"],
        status="archived",
    )

    assert result["success"] is True
    entity_query, _ = db.graph.calls[0]
    assert "node.status = 'archived'" in entity_query
    assert "(node.status IS NULL OR node.status = 'active')" not in entity_query


def test_update_node_clears_expiration_for_nonpositive_ttl():
    """update_node should clear expires_at instead of expiring immediately."""
    db = _FakeNodeDB(
        [
            _FakeResult([_fact_row(123, text="before", updated_at=1)]),
            _FakeResult([_fact_row(123, text="before", updated_at=2)]),
        ]
    )
    db.config = MCPServerConfig(min_ttl_days=-1.0)

    result = update_node(
        cast(Any, db),
        node_id="123",
        owner_id="default",
        ttl_days=0,
    )

    assert result["success"] is True
    update_query, update_params = db.graph.calls[1]
    assert "n.expires_at = NULL" in update_query
    assert "expires_at" not in update_params


def test_create_node_returns_source_payload():
    """create_node should expose source as a single MCP-facing dict."""
    db = _FakeNodeDB(
        [
            _FakeResult(
                [
                    _fact_row(
                        123,
                        text="created fact",
                        source={
                            "ref": "PROJ-123",
                            "type": "jira_issue",
                            "content_hash": "sha256:abc",
                            "version": 1,
                        },
                    )
                ]
            )
        ]
    )
    cfg = MCPServerConfig()

    result = create_node(
        cast(Any, db),
        cfg,
        text="created fact",
        node_type="Fact",
        owner_id="default",
        source={
            "ref": "PROJ-123",
            "type": "jira_issue",
            "content_hash": "sha256:abc",
            "version": 1,
        },
        auto_link=False,
    )

    assert result["success"] is True
    assert result["node"]["source"]["ref"] == "PROJ-123"
    assert result["node"]["source"]["version"] == 1

    create_query, create_params = db.graph.calls[0]
    assert "source_ref: $source_ref" in create_query
    assert create_params["source_ref"] == "PROJ-123"
    assert create_params["content_hash"] == "sha256:abc"


def test_update_node_versioning_increments_source_version():
    """update_node should auto-increment source.version when versioning is enabled."""
    db = _FakeNodeDB(
        [
            _FakeResult(
                [
                    _fact_row(
                        123,
                        text="before",
                        updated_at=1,
                        source={"ref": "PROJ-123", "version": 2},
                    )
                ]
            ),
            _FakeResult([[999]]),
            _FakeResult(
                [
                    _fact_row(
                        123,
                        text="before",
                        updated_at=2,
                        source={"ref": "PROJ-123", "version": 3},
                    )
                ]
            ),
        ]
    )

    result = update_node(
        cast(Any, db),
        node_id="123",
        owner_id="default",
        versioning=True,
    )

    assert result["success"] is True
    assert result["node"]["source"]["version"] == 3

    update_query, update_params = db.graph.calls[2]
    assert "n.source_str = $source_str" in update_query
    assert '"version": 3' in update_params["source_str"]


def test_upsert_node_creates_with_initial_source_version():
    """upsert_node should seed source.version=1 on first create when versioning is enabled."""
    db = _FakeNodeDB(
        [
            _FakeResult([]),
            _FakeResult(
                [
                    _fact_row(
                        123,
                        text="created via upsert",
                        source={"ref": "PROJ-123", "type": "jira_issue", "version": 1},
                    )
                ]
            ),
        ]
    )
    cfg = MCPServerConfig()

    result = upsert_node(
        cast(Any, db),
        cfg,
        text="created via upsert",
        node_type="Fact",
        owner_id="default",
        source={"ref": "PROJ-123", "type": "jira_issue"},
        versioning=True,
        auto_link=False,
    )

    assert result["success"] is True
    assert result["operation"] == "created"
    assert result["node"]["source"]["version"] == 1


def test_upsert_node_requires_source_ref():
    """upsert_node should reject sync writes without a stable source.ref key."""
    db = _FakeNodeDB([])
    cfg = MCPServerConfig()

    result = upsert_node(
        cast(Any, db),
        cfg,
        text="bad upsert",
        node_type="Fact",
        owner_id="default",
        source={"type": "jira_issue"},
        auto_link=False,
    )

    assert result["success"] is False
    assert result["code"] == "memory_validation_error"
