"""Graph store entry point.

`FalkorDBClient` remains the name used across the process. The implementation
lives in `backends.falkor` so a second backend can be added beside it.
"""

from graph_memory_mcp.graph_memory.backends.falkor import FalkorDBClient
from graph_memory_mcp.graph_memory.backends import open_store

__all__ = ["FalkorDBClient", "open_store"]
