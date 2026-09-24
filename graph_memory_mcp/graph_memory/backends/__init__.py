"""Graph backends. Only Falkor is wired up; the factory is the extension point."""

from __future__ import annotations

from typing import Any

from graph_memory_mcp.graph_memory.backends.base import GraphStore
from graph_memory_mcp.graph_memory.backends.falkor import FalkorDBClient

__all__ = ["GraphStore", "FalkorDBClient", "open_store"]


def open_store(config: Any) -> GraphStore:
    """Open the graph backend selected by config.graph_backend (default falkordb)."""
    backend = str(getattr(config, "graph_backend", "falkordb") or "falkordb").strip().lower()
    if backend != "falkordb":
        raise ValueError(
            f"Unknown graph backend {backend!r}. Supported now: falkordb."
        )
    return FalkorDBClient(config)
