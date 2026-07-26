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
# Canonical copy lives in repo docs/ (clone + uv). MCP resource is optional;
# agents should get policy via AGENTS.md / client rules.
_AGENT_POLICIES_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "memory_policies_for_LLM.md"
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
        else:
            # Legacy backfills (uid, Entity name_norm) across all owner graphs.
            try:
                self.db_client.backfill_all_owners()
            except Exception as exc:  # noqa: BLE001
                logger.warning("startup backfill failed: %s", exc)
        try:
            self.embedding_service = EmbeddingService(
                model_name=server_config.embedding_model,
                query_prefix=server_config.embedding_query_prefix,
                passage_prefix=server_config.embedding_passage_prefix,
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
                raise FileNotFoundError(f"Agent policies not found at {policies_path}.")
            return policies_path.read_text(encoding="utf-8")

    def get_mcp_app(self):
        """Get MCP app with /metrics, /admin/* and optional scheduler support."""
        app = self.mcp.streamable_http_app()

        from starlette.routing import Route

        from graph_memory_mcp.metrics import metrics_response

        db = self.db_client
        app.router.routes.append(
            Route("/metrics", lambda request: metrics_response(db), methods=["GET"])
        )
        for route in self._admin_routes():
            app.router.routes.append(route)
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

    def _admin_routes(self) -> list:
        """Operator HTTP endpoints (curl-friendly), separate from agent MCP tools.

        Optional bearer auth via ADMIN_TOKEN; open when unset (trusted env).
        """
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        from graph_memory_mcp.graph_memory import mcp_handlers_admin

        db = self.db_client
        embedding_service = self.embedding_service
        admin_token = self.server_config.admin_token

        def _unauthorized(request) -> JSONResponse | None:
            if not admin_token:
                return None
            if request.headers.get("authorization") == f"Bearer {admin_token}":
                return None
            return JSONResponse(
                {"success": False, "error": "Unauthorized"}, status_code=401
            )

        async def admin_health(request):
            if resp := _unauthorized(request):
                return resp
            return JSONResponse(mcp_handlers_admin.health_check(db, embedding_service))

        async def admin_ensure_indexes(request):
            if resp := _unauthorized(request):
                return resp
            ensure = getattr(self, "ensure_indexes_status", None)
            if ensure is None:
                return JSONResponse(
                    {"success": False, "error": "Not supported"}, status_code=501
                )
            return JSONResponse(ensure())

        async def admin_export(request):
            if resp := _unauthorized(request):
                return resp
            q = request.query_params
            limit = q.get("limit")
            return JSONResponse(
                mcp_handlers_admin.export_owner(
                    db,
                    owner_id=request.path_params["owner_id"],
                    include_embeddings=q.get("include_embeddings", "true") == "true",
                    include_versions=q.get("include_versions", "false") == "true",
                    offset=int(q.get("offset", "0")),
                    limit=int(limit) if limit is not None else None,
                    section=q.get("section", "all"),
                )
            )

        async def admin_import(request):
            if resp := _unauthorized(request):
                return resp
            body = await request.json()
            return JSONResponse(
                mcp_handlers_admin.import_owner(
                    db,
                    owner_id=body.get("owner_id"),
                    nodes=body.get("nodes") or [],
                    relations=body.get("relations"),
                    regenerate_embeddings=bool(body.get("regenerate_embeddings")),
                )
            )

        async def admin_delete_owner(request):
            if resp := _unauthorized(request):
                return resp
            owner_id = request.path_params["owner_id"]
            existed = owner_id in db.list_owners()
            ok = db.delete_owner_graph(owner_id) if existed else False
            return JSONResponse(
                {"success": bool(ok), "owner_id": owner_id, "existed": existed},
                status_code=200 if ok else 404,
            )

        async def admin_prune_empty_owners(request):
            if resp := _unauthorized(request):
                return resp
            pruned = db.prune_empty_owner_graphs()
            return JSONResponse({"success": True, "pruned": pruned})

        return [
            Route("/admin/health", admin_health, methods=["GET"]),
            Route("/admin/ensure-indexes", admin_ensure_indexes, methods=["POST"]),
            Route("/admin/export/{owner_id}", admin_export, methods=["GET"]),
            Route("/admin/import", admin_import, methods=["POST"]),
            Route("/admin/owners/{owner_id}", admin_delete_owner, methods=["DELETE"]),
            Route(
                "/admin/prune-empty-owners", admin_prune_empty_owners, methods=["POST"]
            ),
        ]
