"""
Pytest configuration.

FalkorDB is required except for tests marked ``arcade`` (those need ArcadeDB).
"""

from __future__ import annotations

import pytest
import redis

from graph_memory_mcp.config import load_mcp_server_config


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
