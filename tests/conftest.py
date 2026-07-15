"""
Pytest configuration.

All tests require a running FalkorDB (see docker-compose.yml / scripts/falkordb-up.sh).
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


@pytest.fixture(scope="session", autouse=True)
def require_falkordb() -> None:
    """Fail fast when FalkorDB is not running — required for every test run."""
    cfg = load_mcp_server_config()
    if falkordb_is_available(
        cfg.falkordb_host, cfg.falkordb_port, cfg.falkordb_password
    ):
        return

    pytest.fail(
        "FalkorDB is required but unavailable at "
        f"{cfg.falkordb_host}:{cfg.falkordb_port}. "
        "Start it with: docker compose up -d  (or ./scripts/falkordb-up.sh). "
        "Ensure .env exists (cp env.example .env) and FALKORDB_PASSWORD matches Docker."
    )
