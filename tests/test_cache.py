"""Tests for caching functionality."""

import pytest

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.cache import CacheManager, hash_query


@pytest.fixture
def cache_config():
    """Create config with caching enabled."""
    return MCPServerConfig(
        cache_embeddings_enabled=True,
        cache_embeddings_maxsize=10,
        cache_search_enabled=True,
        cache_search_maxsize=5,
        cache_search_ttl=60,
    )


@pytest.fixture
def cache_manager(cache_config):
    """Create cache manager instance."""
    return CacheManager(cache_config)


def test_embedding_cache_hit_miss(cache_manager):
    """Test embedding cache hit and miss."""
    text = "test embedding"
    embedding = [0.1, 0.2, 0.3]

    # Miss
    assert cache_manager.get_embedding(text) is None

    # Set
    cache_manager.set_embedding(text, embedding)

    # Hit
    cached = cache_manager.get_embedding(text)
    assert cached == embedding


def test_search_cache_hit_miss(cache_manager):
    """Test search cache hit and miss."""
    query_hash = hash_query("test query", owner_id="default", limit=10)
    results = {"success": True, "results": []}

    # Miss
    assert cache_manager.get_search(query_hash) is None

    # Set
    cache_manager.set_search(query_hash, results)

    # Hit
    cached = cache_manager.get_search(query_hash)
    assert cached == results


def test_search_cache_invalidation(cache_manager):
    """Test search cache invalidation."""
    query_hash = hash_query("test query", owner_id="default")
    results = {"success": True, "results": []}

    # Set cache
    cache_manager.set_search(query_hash, results)
    assert cache_manager.get_search(query_hash) is not None

    # Invalidate
    cache_manager.invalidate_search()

    # Cache should be empty
    assert cache_manager.get_search(query_hash) is None


def test_cache_stats(cache_manager, cache_config):
    """Test cache statistics."""
    # Initial stats
    stats = cache_manager.stats()
    assert "embeddings" in stats
    assert "search" in stats
    assert stats["embeddings"]["enabled"] is True
    assert stats["embeddings"]["size"] == 0
    assert stats["search"]["enabled"] is True
    assert stats["search"]["size"] == 0

    # Add items
    cache_manager.set_embedding("text1", [0.1])
    cache_manager.set_embedding("text2", [0.2])
    cache_manager.set_search("hash1", {"results": []})

    # Updated stats
    stats = cache_manager.stats()
    assert stats["embeddings"]["size"] == 2
    assert stats["search"]["size"] == 1


def test_cache_disabled():
    """Test cache with caching disabled."""
    config = MCPServerConfig(
        cache_embeddings_enabled=False,
        cache_search_enabled=False,
    )
    cache_manager = CacheManager(config)

    # Stats should show disabled
    stats = cache_manager.stats()
    assert stats["embeddings"]["enabled"] is False
    assert stats["search"]["enabled"] is False

    # Operations should be no-ops
    cache_manager.set_embedding("text", [0.1])
    assert cache_manager.get_embedding("text") is None

    cache_manager.set_search("hash", {"results": []})
    assert cache_manager.get_search("hash") is None


def test_hash_query_deterministic():
    """Test that hash_query produces deterministic hashes."""
    hash1 = hash_query("query", owner_id="default", limit=10)
    hash2 = hash_query("query", owner_id="default", limit=10)
    assert hash1 == hash2

    # Different params should produce different hash
    hash3 = hash_query("query", owner_id="default", limit=20)
    assert hash1 != hash3


def test_lru_cache_eviction(cache_manager):
    """Test LRU cache eviction when maxsize is reached."""
    # Fill cache to max (10 items)
    for i in range(12):
        cache_manager.set_embedding(f"text{i}", [float(i)])

    # Cache should have max 10 items
    stats = cache_manager.stats()
    assert stats["embeddings"]["size"] == 10

    # Oldest items should be evicted (text0, text1)
    assert cache_manager.get_embedding("text0") is None
    assert cache_manager.get_embedding("text1") is None

    # Newest items should still be there
    assert cache_manager.get_embedding("text11") is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cache_integration(anyio_backend):
    """Test cache integration with actual server."""
    import anyio

    from graph_memory_mcp.config import load_mcp_server_config
    from graph_memory_mcp.server import GraphMemoryMCP

    cfg = load_mcp_server_config()
    async with anyio.create_task_group() as _tg:
        server = GraphMemoryMCP(cfg)

        # Create a node
        # FastMCP.call_tool(name, arguments) -> list of Content objects
        create_response = await server.mcp.call_tool(
            "create_node",
            arguments={"text": "cache test", "node_type": "Fact", "owner_id": "test"},
        )
        assert create_response is not None

        # First search (cache miss)
        search1 = await server.mcp.call_tool(
            "search", arguments={"query": "cache test", "owner_id": "test"}
        )
        assert search1 is not None

        # Check cache stats
        # We can check the cache manager directly instead of health check tool
        stats = server.db_client.cache.stats()
        assert stats["search"]["size"] > 0

        # Second search (cache hit - should be faster)
        search2 = await server.mcp.call_tool(
            "search", arguments={"query": "cache test", "owner_id": "test"}
        )
        assert search2 == search1

        # Create another node (should invalidate cache)
        await server.mcp.call_tool(
            "create_node",
            arguments={"text": "another fact", "node_type": "Fact", "owner_id": "test"},
        )

        # Check cache was invalidated
        stats2 = server.db_client.cache.stats()
        assert stats2["search"]["size"] == 0
