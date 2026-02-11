"""
Comprehensive tests for background jobs (archive, deduplication, scheduler).

Tests cover:
- Archive job: expiring facts with TTL
- Deduplication: finding and merging duplicate facts/entities
- Relation redirection: ensuring relations are properly redirected during merge
- Scheduler lifecycle
"""

import os
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory import mcp_handlers_nodes, mcp_handlers_relations
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService
from graph_memory_mcp.jobs.archive_old_facts import archive_old_facts
from graph_memory_mcp.jobs.deduplicate_facts import (
    _find_duplicate_entity_groups,
    _find_duplicate_fact_groups,
    _merge_duplicate_entities,
    deduplicate_facts,
)
from graph_memory_mcp.jobs.scheduler import (
    get_scheduler_health,
    shutdown_scheduler,
    start_scheduler,
)


@pytest.fixture(scope="module")
def db_client():
    """Shared FalkorDBClient for integration tests to avoid OOM."""
    if os.environ.get("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("integration tests disabled")

    cfg = load_mcp_server_config()
    db = FalkorDBClient(cfg)

    health = db.health_check()
    if health.get("status") != "healthy":
        pytest.skip(f"FalkorDB unavailable: {health.get('error')}")

    # Initialize embedding service once
    db.set_embedding_service(EmbeddingService(model_name=cfg.embedding_model))
    return db


def _falkordb_is_available() -> bool:
    """Check if FalkorDB is available for integration tests."""
    try:
        cfg = load_mcp_server_config()
        db = FalkorDBClient(cfg)
        health = db.health_check()
        return health.get("status") == "healthy"
    except Exception:
        return False


@pytest.mark.asyncio
async def test_scheduler_lifecycle(monkeypatch):
    """Test that scheduler starts and stops correctly based on config."""
    # Mock FalkorDBClient to avoid connection errors
    with patch("graph_memory_mcp.jobs.scheduler.FalkorDBClient") as mock_db_class:
        mock_db = mock_db_class.return_value
        mock_health = MagicMock()
        mock_health.get.return_value = "healthy"
        mock_db.health_check.return_value = mock_health

        # 1. Test disabled by default
        monkeypatch.setenv("JOBS_ENABLED", "false")
        shutdown_scheduler()

        start_scheduler()
        health = get_scheduler_health()
        assert health["running"] is False

        shutdown_scheduler()

        # 2. Test enabled
        monkeypatch.setenv("JOBS_ENABLED", "true")
        monkeypatch.setenv("JOB_DEDUPLICATE_ENABLED", "true")

        shutdown_scheduler()
        start_scheduler()

        health = get_scheduler_health()
        assert health["running"] is True
        assert any(j.get("id") == "deduplicate_facts" for j in health.get("jobs", []))

        shutdown_scheduler()
        time.sleep(0.1)
        health = get_scheduler_health()
        assert health["running"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_archive_job_integration(monkeypatch, db_client):
    """Test archive job with expired TTL facts."""
    owner_id = f"pytest_archive_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("JOBS_ENABLED", "true")
    monkeypatch.setenv("JOB_ARCHIVE_ENABLED", "true")
    monkeypatch.setenv("JOBS_OWNER_IDS", owner_id)

    cfg = load_mcp_server_config()
    db = db_client

    health = db.health_check()
    assert health.get("status") == "healthy"

    db.set_embedding_service(EmbeddingService(model_name=cfg.embedding_model))

    # Create fact with expired TTL
    result = mcp_handlers_nodes.create_node(
        db,
        cfg,
        text="fact to be archived",
        node_type="Fact",
        owner_id=owner_id,
        ttl_days=0.000001,  # Tiny TTL (~0.08s)
    )
    assert result.get("success")
    fact_id = result["node"]["node_id"]

    # Wait for expiration
    time.sleep(0.5)

    # Run archive job
    await archive_old_facts(db=db, config=cfg)

    # Check fact is archived
    get_result = mcp_handlers_nodes.get_node(db, node_id=fact_id, owner_id=owner_id)
    assert get_result.get("success")
    assert get_result["node"]["status"] == "archived"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deduplication_with_relation_redirection(monkeypatch, db_client):
    """
    Test that deduplication properly redirects relations.

    Setup:
    - Create Fact1 (primary)
    - Create Fact2 (duplicate)
    - Create Entity and link to Fact2
    - Run dedup
    - Verify: Fact2 is outdated, Entity now links to Fact1
    """
    owner_id = f"pytest_dedup_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("JOBS_ENABLED", "true")
    monkeypatch.setenv("JOB_DEDUPLICATE_ENABLED", "true")
    monkeypatch.setenv("JOBS_OWNER_IDS", owner_id)

    cfg = load_mcp_server_config()
    db = db_client

    health = db.health_check()
    assert health.get("status") == "healthy"

    db.set_embedding_service(EmbeddingService(model_name=cfg.embedding_model))

    # Create vector indices
    db.create_vector_index()
    db.create_entity_vector_index()

    # Create two identical facts (will be duplicates)
    shared_text = f"duplicate fact text {uuid.uuid4().hex[:8]}"

    result1 = mcp_handlers_nodes.create_node(
        db,
        cfg,
        text=shared_text,
        node_type="Fact",
        owner_id=owner_id,
        auto_link=False,
    )
    assert result1.get("success")
    fact1_id = result1["node"]["node_id"]

    time.sleep(0.1)  # Ensure different timestamps

    result2 = mcp_handlers_nodes.create_node(
        db,
        cfg,
        text=shared_text,
        node_type="Fact",
        owner_id=owner_id,
        auto_link=False,
    )
    assert result2.get("success")
    fact2_id = result2["node"]["node_id"]

    # Create entity linked to Fact2
    entity_result = mcp_handlers_nodes.create_node(
        db,
        cfg,
        text="test entity",
        node_type="Entity",
        owner_id=owner_id,
        auto_link=False,
    )
    assert entity_result.get("success")
    entity_id = entity_result["node"]["node_id"]

    # Create relation: Fact2 -> Entity
    rel_result = mcp_handlers_relations.create_relation(
        db,
        from_id=fact2_id,
        to_id=entity_id,
        relation_type="MENTIONS",
        owner_id=owner_id,
    )
    assert rel_result.get("success")

    # Verify relation exists before dedup
    query_before = f"""
    MATCH (f:Fact)-[r:MENTIONS]->(e:Entity)
    WHERE id(f) = {int(fact2_id)} AND id(e) = {int(entity_id)}
    RETURN count(r) as cnt
    """
    result_before = db.graph.query(query_before)
    assert result_before.result_set[0][0] == 1

    # Run deduplication
    await deduplicate_facts(db=db, config=cfg)

    # Verify Fact2 is marked as outdated
    get_fact2 = mcp_handlers_nodes.get_node(db, node_id=fact2_id, owner_id=owner_id)
    assert get_fact2.get("success")
    assert get_fact2["node"]["status"] == "outdated"

    # Verify Fact1 is still active
    get_fact1 = mcp_handlers_nodes.get_node(db, node_id=fact1_id, owner_id=owner_id)
    assert get_fact1.get("success")
    assert get_fact1["node"]["status"] == "active"

    # Verify relation was redirected from Fact2 to Fact1
    query_after = f"""
    MATCH (f:Fact)-[r:MENTIONS]->(e:Entity)
    WHERE id(f) = {int(fact1_id)} AND id(e) = {int(entity_id)}
    RETURN count(r) as cnt
    """
    result_after = db.graph.query(query_after)
    assert result_after.result_set[0][0] == 1, "Relation should be redirected to Fact1"

    # Verify old relation from Fact2 is gone
    query_old = f"""
    MATCH (f:Fact)-[r:MENTIONS]->(e:Entity)
    WHERE id(f) = {int(fact2_id)} AND id(e) = {int(entity_id)}
    RETURN count(r) as cnt
    """
    result_old = db.graph.query(query_old)
    assert result_old.result_set[0][0] == 0, "Old relation from Fact2 should be deleted"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_entity_deduplication(monkeypatch, db_client):
    """Test entity deduplication."""
    owner_id = f"pytest_entity_dedup_{uuid.uuid4().hex[:8]}"

    cfg = load_mcp_server_config()
    db = db_client

    health = db.health_check()
    assert health.get("status") == "healthy"

    db.set_embedding_service(EmbeddingService(model_name=cfg.embedding_model))
    db.create_entity_vector_index()

    # Create duplicate entities
    shared_text = f"duplicate entity {uuid.uuid4().hex[:8]}"

    result1 = mcp_handlers_nodes.create_node(
        db,
        cfg,
        text=shared_text,
        node_type="Entity",
        owner_id=owner_id,
        auto_link=False,
    )
    assert result1.get("success")
    entity1_id = result1["node"]["node_id"]

    time.sleep(0.1)

    result2 = mcp_handlers_nodes.create_node(
        db,
        cfg,
        text=shared_text,
        node_type="Entity",
        owner_id=owner_id,
        auto_link=False,
    )
    assert result2.get("success")
    entity2_id = result2["node"]["node_id"]

    # Find duplicates
    groups = await _find_duplicate_entity_groups(
        db,
        threshold=0.95,
        max_group_size=2,
        owner_id=owner_id,
        hours_threshold=24,
    )

    assert len(groups) > 0, "Should find duplicate entity groups"

    # Merge duplicates
    result_id = await _merge_duplicate_entities(
        db,
        entity_ids=[entity1_id, entity2_id],
        owner_id=owner_id,
    )

    assert result_id == entity1_id

    # Verify entity2 is outdated
    get_entity2 = mcp_handlers_nodes.get_node(db, node_id=entity2_id, owner_id=owner_id)
    assert get_entity2.get("success")
    assert get_entity2["node"]["status"] == "outdated"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_duplicate_fact_groups(monkeypatch, db_client):
    """Test finding duplicate fact groups."""
    owner_id = f"pytest_find_dupes_{uuid.uuid4().hex[:8]}"

    cfg = load_mcp_server_config()
    db = db_client

    health = db.health_check()
    assert health.get("status") == "healthy"

    db.set_embedding_service(EmbeddingService(model_name=cfg.embedding_model))
    db.create_vector_index()

    # Create duplicate facts
    shared_text = f"find duplicate test {uuid.uuid4().hex[:8]}"

    for _ in range(3):
        result = mcp_handlers_nodes.create_node(
            db,
            cfg,
            text=shared_text,
            node_type="Fact",
            owner_id=owner_id,
            auto_link=False,
        )
        assert result.get("success")
        time.sleep(0.05)

    # Find duplicates
    groups = await _find_duplicate_fact_groups(
        db,
        threshold=0.95,
        max_group_size=2,
        owner_id=owner_id,
        hours_threshold=24,
    )

    assert len(groups) > 0, "Should find duplicate fact groups"
    assert all("primary_id" in g and "duplicate_ids" in g for g in groups)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_archive_respects_active_relations(monkeypatch, db_client):
    """Test that archive job doesn't archive facts with active relations."""
    owner_id = f"pytest_archive_rel_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("JOBS_ENABLED", "true")
    monkeypatch.setenv("JOB_ARCHIVE_ENABLED", "true")
    monkeypatch.setenv("JOBS_OWNER_IDS", owner_id)

    cfg = load_mcp_server_config()
    db = db_client

    health = db.health_check()
    assert health.get("status") == "healthy"

    db.set_embedding_service(EmbeddingService(model_name=cfg.embedding_model))

    # Create fact with expired TTL
    result = mcp_handlers_nodes.create_node(
        db,
        cfg,
        text="fact with relation",
        node_type="Fact",
        owner_id=owner_id,
        ttl_days=0.000001,
        auto_link=False,
    )
    assert result.get("success")
    fact_id = result["node"]["node_id"]

    # Create entity and link to fact
    entity_result = mcp_handlers_nodes.create_node(
        db,
        cfg,
        text="linked entity",
        node_type="Entity",
        owner_id=owner_id,
        auto_link=False,
    )
    assert entity_result.get("success")
    entity_id = entity_result["node"]["node_id"]

    rel_result = mcp_handlers_relations.create_relation(
        db,
        from_id=fact_id,
        to_id=entity_id,
        relation_type="MENTIONS",
        owner_id=owner_id,
    )
    assert rel_result.get("success")

    # Wait for expiration
    time.sleep(0.5)

    # Run archive job
    await archive_old_facts(db=db, config=cfg)

    # Fact should NOT be archived because it has active relation to Entity
    get_result = mcp_handlers_nodes.get_node(db, node_id=fact_id, owner_id=owner_id)
    assert get_result.get("success")
    assert (
        get_result["node"]["status"] == "active"
    ), "Fact with active Entity relation should not be archived"
