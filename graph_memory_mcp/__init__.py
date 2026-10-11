"""Graph Memory MCP package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("graph-memory-mcp")
except PackageNotFoundError:  # running from a plain checkout without install
    __version__ = "0.0.0"
