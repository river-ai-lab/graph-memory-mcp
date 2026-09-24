"""
Pytest configuration.

Tests need a running FalkorDB unless they are marked ``vela`` (embedded backend).
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


_FALKOR_OK: bool | None = None


@pytest.fixture(autouse=True)
def require_falkordb(request: pytest.FixtureRequest) -> None:
    """Fail fast when FalkorDB is not running. Vela tests do not need it."""
    if request.node.get_closest_marker("vela"):
        return
    global _FALKOR_OK
    cfg = load_mcp_server_config()
    if _FALKOR_OK is None:
        _FALKOR_OK = falkordb_is_available(
            cfg.falkordb_host, cfg.falkordb_port, cfg.falkordb_password
        )
    if _FALKOR_OK:
        return

    pytest.fail(
        "FalkorDB is required but unavailable at "
        f"{cfg.falkordb_host}:{cfg.falkordb_port}. "
        "Start it with: docker compose up -d  (or ./scripts/falkordb-up.sh). "
        "Ensure .env exists (cp env.example .env) and FALKORDB_PASSWORD matches Docker."
    )
