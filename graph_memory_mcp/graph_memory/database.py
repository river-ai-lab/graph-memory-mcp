"""Graph store entry point.

`FalkorDBClient` remains the name used across handlers. `open_store` picks
FalkorDB or Vela from `GRAPH_BACKEND` (default `falkordb`).
"""

from graph_memory_mcp.graph_memory.backends.falkor import FalkorDBClient
from graph_memory_mcp.graph_memory.backends import open_store

__all__ = ["FalkorDBClient", "open_store"]
