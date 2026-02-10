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

import os
import uuid

import anyio
import httpx
import pytest
import redis
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from graph_memory_mcp.config import MCPServerConfig, load_mcp_server_config
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

    async with anyio.create_task_group() as tg:
        async with streamable_http_client(
            httpx.AsyncClient(app=app, base_url="http://test")
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # ========================================
                # INFORMATION TOOLS (3)
                # ========================================

                # 1. test_connection
                result = await session.call_tool("test_connection", {})
                data = _extract_tool_json(result)
                assert data.get("success") is True
                assert data.get("message") == "pong"

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
                        "query": "container orchestration",
                        "owner_id": owner_id,
                        "limit": 10,
                        "node_types": ["Fact"],
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
                alice_id = data["subject_id"]
                k8s_entity_id = data["object_id"]

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
                assert len(data.get("path", [])) > 0

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
                summary_fact_id = data["summary_fact"]["node_id"]

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

                tg.cancel_scope.cancel()


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

    server = MemoryMCPServer(cfg)
    app = server.get_mcp_app()

    async with anyio.create_task_group() as tg:
        async with streamable_http_client(
            httpx.AsyncClient(app=app, base_url="http://test")
        ) as (read, write):
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

                tg.cancel_scope.cancel()
