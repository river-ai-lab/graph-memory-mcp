"""
Pytest configuration.

FalkorDB is required except for tests marked ``arcade`` (those need ArcadeDB).
``memory_backend`` runs a test once on each store.
"""

from __future__ import annotations

import os

import pytest
import redis

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory.database import open_store
from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService


def falkordb_is_available(host: str, port: int, password: str | None) -> bool:
    """Return True if FalkorDB/Redis accepts connections."""
    try:
        client = redis.Redis(
            host=host,
            port=port,
            password=password or None,
            socket_timeout=2.0,
        )
        return client.ping() is True
    except Exception:
        return False


_falkor_up: bool | None = None


@pytest.fixture(autouse=True)
def require_falkordb(request: pytest.FixtureRequest) -> None:
    """FalkorDB is required for tests that are not marked arcade."""
    if request.node.get_closest_marker("arcade"):
        return
    global _falkor_up
    if _falkor_up is None:
        cfg = load_mcp_server_config()
        _falkor_up = falkordb_is_available(
            cfg.falkordb_host, cfg.falkordb_port, cfg.falkordb_password
        )
    if _falkor_up:
        return
    cfg = load_mcp_server_config()
    pytest.fail(
        "FalkorDB is required but unavailable at "
        f"{cfg.falkordb_host}:{cfg.falkordb_port}. "
        "Start it with: docker compose up -d  (or ./scripts/falkordb-up.sh). "
        "Ensure .env exists (cp env.example .env) and FALKORDB_PASSWORD matches Docker."
    )


@pytest.fixture(autouse=True)
def select_graph_backend(request, monkeypatch):
    """Unmarked tests talk to FalkorDB. Arcade-marked tests talk to ArcadeDB.

    Compose and CI use the ArcadeDB password ``playwithdata``. A different
    value in ``.env`` must not be sent: several failures lock the account.
    """
    if request.node.get_closest_marker("arcade"):
        monkeypatch.setenv("GRAPH_BACKEND", "arcadedb")
        monkeypatch.setenv("ARCADE_PASSWORD", "playwithdata")
    else:
        monkeypatch.setenv("GRAPH_BACKEND", "falkordb")
        if not os.environ.get("FALKORDB_PASSWORD"):
            monkeypatch.setenv("FALKORDB_PASSWORD", "falkordb123")


class MemoryBackend:
    """One configured store. Tests that take this fixture run on both backends."""

    def __init__(self, config, db) -> None:
        self.config = config
        self.db = db


@pytest.fixture(scope="session")
def embedding_service():
    cfg = load_mcp_server_config()
    return EmbeddingService(model_name=cfg.embedding_model)


@pytest.fixture(params=["falkordb", pytest.param("arcadedb", marks=pytest.mark.arcade)])
def graph_backend(request) -> str:
    return request.param


@pytest.fixture
def memory_backend(graph_backend: str, embedding_service) -> MemoryBackend:
    """Open FalkorDB or ArcadeDB. Arcade uses the Compose password."""
    cfg = load_mcp_server_config().model_copy(update={"graph_backend": graph_backend})
    if graph_backend == "arcadedb":
        cfg = cfg.model_copy(update={"arcade_password": "playwithdata"})
    db = open_store(cfg)
    if not db.connect():
        if graph_backend == "arcadedb":
            pytest.fail(
                "ArcadeDB is required but unavailable at "
                f"{cfg.arcade_host}:{cfg.arcade_port}. "
                "Start it with: docker compose up -d"
            )
        pytest.fail(
            "FalkorDB is required but unavailable at "
            f"{cfg.falkordb_host}:{cfg.falkordb_port}."
        )
    db.set_embedding_service(embedding_service)
    return MemoryBackend(cfg, db)
