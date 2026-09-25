"""Graph store entry point.

`FalkorDBClient` remains the name used across the process. `open_store`
selects FalkorDB (default) or ArcadeDB.
"""

from graph_memory_mcp.graph_memory.backends.falkor import FalkorDBClient
from graph_memory_mcp.graph_memory.backends import open_store

__all__ = ["FalkorDBClient", "open_store"]
