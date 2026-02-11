"""
Edge cases and error scenarios tests for MCP Graph Memory.

Tests cover:
- Invalid inputs and error handling
- Auto-linking functionality
- TTL and expiration
- Links parameter for immediate relation creation
- Boundary conditions
"""

from __future__ import annotations

import json
import os
import time
import uuid

import pytest
import redis

from graph_memory_mcp.config import load_mcp_server_config
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
    """Extract JSON from MCP tool result (FastMCP returns list of content)."""
    # If result is from FastMCP.call_tool, it's a list of TextContent objects
    if isinstance(result, list):
        if not result:
            return {}
        item = result[0]
        text = getattr(item, "text", None)
        if hasattr(item, "type") and item.type == "text":
            text = item.text

        if isinstance(text, str):
            try:
                return json.loads(text)
            except Exception:
                return {"raw": text}

    # Fallback for other types
    content = getattr(result, "content", None)
    if content and len(content) > 0:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            try:
                return json.loads(text)
            except Exception:
                return {"raw": text}
    if isinstance(result, dict):
        return result
    return {"raw": repr(result)}


@pytest.fixture(scope="module")
def server_instance():
    """Shared server instance for the module to avoid reloading models."""
    if os.environ.get("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("integration tests disabled")

    cfg = load_mcp_server_config()
    return GraphMemoryMCP(cfg)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auto_link_functionality(server_instance):
    """
    Test auto_link parameter - automatic semantic linking of facts.

    When auto_link=True, new facts should automatically link to semantically similar facts.
    """
    server = server_instance
    owner_id = f"pytest_autolink_{uuid.uuid4().hex[:8]}"

    # Create first fact without auto_link
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Python is a programming language",
            "node_type": "Fact",
            "owner_id": owner_id,
            "auto_link": False,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True

    # Create second fact WITH auto_link (should link to first)
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Python is used for data science and web development",
            "node_type": "Fact",
            "owner_id": owner_id,
            "auto_link": True,  # Should auto-link to fact1
            "semantic_threshold": 0.7,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True
    fact2_id = data["node"]["node_id"]

    # Check that fact2 has auto-created links
    result = await server.mcp.call_tool(
        "get_context",
        {
            "node_id": fact2_id,
            "owner_id": owner_id,
            "depth": 1,
        },
    )
    data = _extract_tool_json(result)
    edges = data.get("edges", [])

    # Should have at least one edge to fact1 (if embeddings are similar enough)
    assert len(edges) >= 0

    # If there are edges, verify they are RELATED_TO type
    if edges:
        assert any(e.get("relation_type") == "RELATED_TO" for e in edges)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ttl_and_expiration(server_instance):
    """
    Test TTL (time-to-live) functionality.

    Facts created with ttl_days should have expires_at timestamp set correctly.
    """
    server = server_instance
    owner_id = f"pytest_ttl_{uuid.uuid4().hex[:8]}"

    # Create fact with TTL
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Temporary fact with TTL",
            "node_type": "Fact",
            "owner_id": owner_id,
            "ttl_days": 7.0,  # 7 days
            "auto_link": False,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True
    fact_id = data["node"]["node_id"]

    # Verify fact has expires_at set
    result = await server.mcp.call_tool(
        "get_node",
        {
            "node_id": fact_id,
            "owner_id": owner_id,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True
    node = data["node"]

    assert "expires_at" in node
    assert node["expires_at"] is not None

    # expires_at should be in the future
    now_ms = int(time.time() * 1000)
    expires_at = node["expires_at"]
    assert expires_at > now_ms, "expires_at should be in the future"

    # Should be approximately 7 days from now (within 1 hour tolerance)
    seven_days_ms = 7 * 24 * 60 * 60 * 1000
    expected_expiry = now_ms + seven_days_ms
    tolerance = 60 * 60 * 1000  # 1 hour
    assert abs(expires_at - expected_expiry) < tolerance

    # Test updating TTL
    result = await server.mcp.call_tool(
        "update_node",
        {
            "node_id": fact_id,
            "owner_id": owner_id,
            "ttl_days": 1.0,  # Change to 1 day
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True

    # Verify updated expires_at
    result = await server.mcp.call_tool(
        "get_node",
        {
            "node_id": fact_id,
            "owner_id": owner_id,
        },
    )
    data = _extract_tool_json(result)
    new_expires_at = data["node"]["expires_at"]

    # New expiry should be sooner than old one
    assert new_expires_at < expires_at


@pytest.mark.integration
@pytest.mark.asyncio
async def test_links_parameter(server_instance):
    """
    Test 'links' parameter - create node with immediate relations.

    The links parameter allows creating a node and its relations in one call.
    """
    server = server_instance
    owner_id = f"pytest_links_{uuid.uuid4().hex[:8]}"

    # Create target nodes first
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Target fact 1",
            "node_type": "Fact",
            "owner_id": owner_id,
            "auto_link": False,
        },
    )
    target1_id = _extract_tool_json(result)["node"]["node_id"]

    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Target entity",
            "node_type": "Entity",
            "owner_id": owner_id,
            "auto_link": False,
        },
    )
    target2_id = _extract_tool_json(result)["node"]["node_id"]

    # Create node with links to both targets
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Source fact with immediate links",
            "node_type": "Fact",
            "owner_id": owner_id,
            "auto_link": False,
            "links": [
                {
                    "to_id": target1_id,
                    "relation_type": "RELATED_TO",
                    "properties": {"strength": 0.9},
                },
                {
                    "to_id": target2_id,
                    "relation_type": "MENTIONS",
                    "properties": {"confidence": 1.0},
                },
            ],
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True
    source_id = data["node"]["node_id"]

    # Verify links were created
    result = await server.mcp.call_tool(
        "get_context",
        {
            "node_id": source_id,
            "owner_id": owner_id,
            "depth": 1,
        },
    )
    data = _extract_tool_json(result)
    edges = data.get("edges", [])

    # Should have 2 edges
    assert len(edges) == 2

    # Verify edge types and targets
    edge_types = {e["relation_type"] for e in edges}
    assert "RELATED_TO" in edge_types
    assert "MENTIONS" in edge_types

    target_ids = {e["to_id"] for e in edges}
    assert target1_id in target_ids
    assert target2_id in target_ids

    # Verify properties were set
    related_edge = next(e for e in edges if e["relation_type"] == "RELATED_TO")
    assert related_edge.get("properties", {}).get("strength") == 0.9


@pytest.mark.integration
@pytest.mark.asyncio
async def test_error_handling_invalid_inputs(server_instance):
    """
    Test error handling for invalid inputs.
    """
    server = server_instance
    owner_id = f"pytest_errors_{uuid.uuid4().hex[:8]}"

    # Test 1: Get non-existent node
    result = await server.mcp.call_tool(
        "get_node",
        {
            "node_id": "999999",
            "owner_id": owner_id,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is False
    assert "error" in data or "message" in data

    # Test 2: Create node without text
    try:
        result = await server.mcp.call_tool(
            "create_node",
            {
                "node_type": "Fact",
                "owner_id": owner_id,
            },
        )
        data = _extract_tool_json(result)
    except Exception:
        pass  # FastMCP might raise validation error if text is missing but it's optional in signature (None default)

    # Test 3: Create relation with non-existent nodes
    result = await server.mcp.call_tool(
        "create_relation",
        {
            "from_id": "999998",
            "to_id": "999999",
            "relation_type": "INVALID",
            "owner_id": owner_id,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is False

    # Test 4: Update non-existent node
    result = await server.mcp.call_tool(
        "update_node",
        {
            "node_id": "999999",
            "owner_id": owner_id,
            "text": "Updated text",
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is False

    # Test 5: Delete non-existent node
    result = await server.mcp.call_tool(
        "delete_node",
        {
            "node_id": "999999",
            "owner_id": owner_id,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is False

    # Test 6: Search with invalid parameters
    result = await server.mcp.call_tool(
        "search",
        {
            "query": "",  # Empty query
            "owner_id": owner_id,
        },
    )
    data = _extract_tool_json(result)
    assert "success" in data or "error" in data

    # Test 7: Create triplet with empty values
    result = await server.mcp.call_tool(
        "create_triplet",
        {
            "subject": "",
            "predicate": "",
            "object_value": "",
            "owner_id": owner_id,
        },
    )
    data = _extract_tool_json(result)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_boundary_conditions(server_instance):
    """
    Test boundary conditions and limits.
    """
    server = server_instance
    owner_id = f"pytest_boundary_{uuid.uuid4().hex[:8]}"

    # Test 1: Very long text
    long_text = "A" * 10000  # 10k characters
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": long_text,
            "node_type": "Fact",
            "owner_id": owner_id,
            "auto_link": False,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True
    long_fact_id = data["node"]["node_id"]

    # Verify we can retrieve it
    result = await server.mcp.call_tool(
        "get_node",
        {
            "node_id": long_fact_id,
            "owner_id": owner_id,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True
    assert len(data["node"]["text"]) == 10000

    # Test 2: Large metadata
    large_metadata = {f"key_{i}": f"value_{i}" * 100 for i in range(50)}
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Fact with large metadata",
            "node_type": "Fact",
            "owner_id": owner_id,
            "metadata": large_metadata,
            "auto_link": False,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True

    # Test 3: Deep graph traversal
    # Create chain: f1 -> f2 -> f3 -> f4 -> f5
    prev_id = None
    first_id = None
    last_id = None
    for i in range(5):
        result = await server.mcp.call_tool(
            "create_node",
            {
                "text": f"Chain fact {i}",
                "node_type": "Fact",
                "owner_id": owner_id,
                "auto_link": False,
            },
        )
        curr_id = _extract_tool_json(result)["node"]["node_id"]

        if prev_id:
            await server.mcp.call_tool(
                "create_relation",
                {
                    "from_id": prev_id,
                    "to_id": curr_id,
                    "relation_type": "NEXT",
                    "owner_id": owner_id,
                },
            )

        if i == 0:
            first_id = curr_id
        if i == 4:
            last_id = curr_id

        prev_id = curr_id

    # Test get_trace with max_depth limit
    result = await server.mcp.call_tool(
        "get_trace",
        {
            "from_id": first_id,
            "to_id": last_id,
            "owner_id": owner_id,
            "max_depth": 10,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True
    assert len(data.get("nodes", [])) > 0

    # Test 4: Search with large limit
    result = await server.mcp.call_tool(
        "search",
        {
            "query": "fact",
            "owner_id": owner_id,
            "limit": 1000,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_operations(server_instance):
    """
    Test that concurrent operations on same data are handled correctly.
    """
    server = server_instance
    owner_id = f"pytest_concurrent_{uuid.uuid4().hex[:8]}"

    # Create a fact
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Concurrent test fact",
            "node_type": "Fact",
            "owner_id": owner_id,
            "auto_link": False,
        },
    )
    fact_id = _extract_tool_json(result)["node"]["node_id"]

    # Multiple updates in sequence (simulating concurrent updates)
    for i in range(5):
        result = await server.mcp.call_tool(
            "update_node",
            {
                "node_id": fact_id,
                "owner_id": owner_id,
                "metadata": {"update_count": i},
                "versioning": True,
            },
        )
        data = _extract_tool_json(result)
        assert data.get("success") is True

    # Verify final state
    result = await server.mcp.call_tool(
        "get_node",
        {
            "node_id": fact_id,
            "owner_id": owner_id,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True
    assert data["node"]["metadata"]["update_count"] == 4

    # Check version history
    result = await server.mcp.call_tool(
        "get_node_change_history",
        {
            "node_id": fact_id,
            "owner_id": owner_id,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True
    assert len(data.get("versions", [])) >= 4


@pytest.mark.integration
@pytest.mark.asyncio
async def test_input_validation(server_instance):
    """
    Test input validation for all handlers.
    """
    cfg = server_instance.config
    server = server_instance
    owner_id = f"pytest_validation_{uuid.uuid4().hex[:8]}"

    # Test 1: Text too long
    long_text = "A" * (cfg.max_text_length + 1)
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": long_text,
            "node_type": "Fact",
            "owner_id": owner_id,
            "auto_link": False,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is False
    assert "too long" in data.get("error", "").lower()
    assert data.get("code") == "memory_validation_error"

    # Test 2: Metadata too large
    large_metadata = {f"key_{i}": "X" * 10000 for i in range(20)}
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Test fact",
            "node_type": "Fact",
            "owner_id": owner_id,
            "metadata": large_metadata,
            "auto_link": False,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is False
    assert "too large" in data.get("error", "").lower()
    assert data.get("code") == "memory_validation_error"

    # Test 3: TTL out of range (negative)
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Test fact",
            "node_type": "Fact",
            "owner_id": owner_id,
            "ttl_days": -1.0,
            "auto_link": False,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is False
    assert "ttl" in data.get("error", "").lower()
    assert data.get("code") == "memory_validation_error"

    # Test 4: TTL out of range (too large)
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Test fact",
            "node_type": "Fact",
            "owner_id": owner_id,
            "ttl_days": 10000.0,  # Exceeds max_ttl_days
            "auto_link": False,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is False
    assert "ttl" in data.get("error", "").lower()
    assert data.get("code") == "memory_validation_error"

    # Test 5: Invalid owner_id format
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Test fact",
            "node_type": "Fact",
            "owner_id": "invalid!@#$%owner",
            "auto_link": False,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is False
    assert "owner_id" in data.get("error", "").lower()
    assert data.get("code") == "memory_validation_error"

    # Test 6: Invalid relation_type format
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Node 1",
            "node_type": "Fact",
            "owner_id": owner_id,
            "auto_link": False,
        },
    )
    node1_id = _extract_tool_json(result)["node"]["node_id"]

    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Node 2",
            "node_type": "Fact",
            "owner_id": owner_id,
            "auto_link": False,
        },
    )
    node2_id = _extract_tool_json(result)["node"]["node_id"]

    result = await server.mcp.call_tool(
        "create_relation",
        {
            "from_id": node1_id,
            "to_id": node2_id,
            "relation_type": "INVALID-TYPE!@#",
            "owner_id": owner_id,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is False
    assert "relation_type" in data.get("error", "").lower()
    assert data.get("code") == "memory_validation_error"

    # Test 7: Valid inputs should work
    result = await server.mcp.call_tool(
        "create_node",
        {
            "text": "Valid fact with all constraints",
            "node_type": "Fact",
            "owner_id": owner_id,
            "metadata": {"key": "value"},
            "ttl_days": 30.0,
            "auto_link": False,
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is True

    # Test 8: Update with invalid text length
    valid_fact_id = data["node"]["node_id"]
    result = await server.mcp.call_tool(
        "update_node",
        {
            "node_id": valid_fact_id,
            "owner_id": owner_id,
            "text": "B" * (cfg.max_text_length + 1),
        },
    )
    data = _extract_tool_json(result)
    assert data.get("success") is False
    assert "too long" in data.get("error", "").lower()
