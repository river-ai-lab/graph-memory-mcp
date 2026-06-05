"""
Base MCP Graph Memory server - shared functionality.

This module contains the base class with common functionality
shared between server.py and server_extended.py.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService
from graph_memory_mcp.jobs.scheduler import shutdown_scheduler, start_scheduler

logger = logging.getLogger(__name__)

_AGENT_POLICIES_URI = "graph-memory://agent-policies"
_AGENT_POLICIES_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "memory_policies_for_LLM.md"
)

# Shown to MCP clients at connect (see MCP spec: server instructions).
_MCP_INSTRUCTIONS = (
    "Graph Memory is a long-term knowledge graph, not a chat log. "
    "Always pass owner_id explicitly on reads and writes (alphanumeric, _, -, @). "
    "Search before create; store one durable declarative fact per node. "
    "Never store chat logs, secrets, or ephemeral execution state. "
    "For substantive changes: mark_outdated then create_node. "
    f"Before the first memory write in a session, read MCP resource {_AGENT_POLICIES_URI}."
)


class _UnavailableEmbeddingService:
    """Fallback embedding service used when model cannot be loaded."""

    dimension = 0

    def get_embedding(self, text: str):  # type: ignore[no-untyped-def]
        raise RuntimeError("Embeddings model is not available")

    def get_embeddings_batch(self, texts):  # type: ignore[no-untyped-def]
        raise RuntimeError("Embeddings model is not available")


class BaseGraphMemoryMCP:
    """Base Graph Memory MCP Server with shared functionality."""

    def __init__(self, server_config: MCPServerConfig):
        self.server_config = server_config
        self.config = server_config
        self.db_client = FalkorDBClient(server_config)
        self._db_connected = self.db_client.connect()
        if not self._db_connected:
            logger.warning(
                "Failed to connect to FalkorDB (host=%s, port=%s, graph=%s). "
                "Memory tools will operate in degraded mode.",
                server_config.falkordb_host,
                server_config.falkordb_port,
                server_config.falkordb_graph,
            )
        try:
            self.embedding_service = EmbeddingService(
                model_name=server_config.embedding_model
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to load embeddings model: %s", exc)
            self.embedding_service = _UnavailableEmbeddingService()

        self.db_client.set_embedding_service(self.embedding_service)

        self.mcp = FastMCP(
            name=self.server_config.description or self.server_config.name,
            instructions=_MCP_INSTRUCTIONS,
            stateless_http=True,
            json_response=True,
        )
        self._register_resources()
        self._register_tools()

    def _register_resources(self) -> None:
        """Expose agent policy docs as an MCP resource."""
        mcp = self.mcp
        policies_path = _AGENT_POLICIES_PATH

        @mcp.resource(
            _AGENT_POLICIES_URI,
            name="agent-policies",
            title="Agent Memory Directives",
            description=(
                "Full read/write policy for Graph Memory: owner_id scope, what to store, "
                "search-before-create, relations, and update protocol."
            ),
            mime_type="text/markdown",
        )
        def agent_policies() -> str:
            if not policies_path.is_file():
                raise FileNotFoundError(
                    f"Agent policies not found at {policies_path}. "
                    "Run the server from a repo checkout that includes docs/."
                )
            return policies_path.read_text(encoding="utf-8")

    def get_mcp_app(self):
        """Get MCP app with optional background scheduler support."""
        app = self.mcp.streamable_http_app()
        # Wire background scheduler into Starlette lifespan (config-driven).
        cfg = self.server_config.config or {}
        jobs_enabled = bool(cfg.get("jobs_enabled", False))
        if jobs_enabled:
            # Preserve original lifespan context only once
            if getattr(app.state, "_memory_jobs_wrapped", False):
                return app
            setattr(app.state, "_memory_jobs_wrapped", True)

            orig = getattr(app.router, "lifespan_context", None)

            @asynccontextmanager
            async def _lifespan(app_obj):  # type: ignore[no-untyped-def]
                if orig is not None:
                    async with orig(app_obj):
                        start_scheduler()
                        try:
                            yield
                        finally:
                            shutdown_scheduler()
                else:
                    start_scheduler()
                    try:
                        yield
                    finally:
                        shutdown_scheduler()

            app.router.lifespan_context = _lifespan  # type: ignore[attr-defined]
        return app

    def _register_tools(self) -> None:
        """Register all MCP tools. To be overridden by subclasses."""
        raise NotImplementedError("Subclasses must implement _register_tools()")
