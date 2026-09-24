"""Graph backends. FalkorDB is the default; Vela is the embedded alternative."""

from __future__ import annotations

from typing import Any

from graph_memory_mcp.graph_memory.backends.base import GraphStore
from graph_memory_mcp.graph_memory.backends.falkor import FalkorDBClient

__all__ = ["GraphStore", "FalkorDBClient", "open_store"]


def open_store(config: Any) -> GraphStore:
    """Open the graph backend selected by config.graph_backend (default falkordb)."""
    backend = str(getattr(config, "graph_backend", "falkordb") or "falkordb").strip().lower()
    if backend == "falkordb":
        return FalkorDBClient(config)
    if backend == "vela":
        from graph_memory_mcp.graph_memory.backends.vela import VelaClient

        return VelaClient(config)
    raise ValueError(
        f"Unknown graph backend {backend!r}. Supported: falkordb, vela."
    )
