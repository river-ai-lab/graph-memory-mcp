"""
Base MCP Graph Memory server - shared functionality.

This module contains the base class with common functionality
shared by the default, simple, and extended MCP profiles.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.api_keys import validate_token_mode
from graph_memory_mcp.graph_memory.database import open_store
from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService
from graph_memory_mcp.graph_memory.owner_scope import (
    OwnerHeaderMiddleware,
    OwnerTokenMiddleware,
    authenticate,
    configure_owner_scope,
)
from graph_memory_mcp.jobs.scheduler import shutdown_scheduler, start_scheduler

logger = logging.getLogger(__name__)

_AGENT_POLICIES_URI = "graph-memory://agent-policies"
# Canonical copy lives in repo docs/ (clone + uv). MCP resource is optional;
# put these operator constants in your own AGENTS.md (docs/AGENTS_example.md).
_AGENT_POLICIES_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "memory_policies_for_LLM.md"
)


def _mcp_instructions(scope: str, *, hide_owner: bool = False) -> str:
    """Mode-specific text shown to MCP clients at connect.

    ``hide_owner`` is the ``--auth`` entry: the schema has no ``owner_id``.
    """
    common = (
        "Graph Memory is a long-term knowledge graph, not a chat log. "
        "Search before create; store one durable declarative fact per node. "
        "Never store chat logs, secrets, or ephemeral execution state. "
        "For substantive changes: mark_outdated then create_node. "
        "source_updated_at is the source document time in Unix milliseconds, "
        "not the server-managed updated_at. "
        f"Before the first memory write in a session, read MCP resource {_AGENT_POLICIES_URI}."
    )
    mode = str(scope or "client").strip().lower()
    if hide_owner:
        return (
            f"{common} The server sets owner_id from the API key. Do not pass it. "
            "The server sets created_by and updated_by from the API key name."
        )
    if mode == "token":
        return (
            f"{common} The server sets created_by and updated_by from the API key "
            "name. Pass owner_id only to choose among the key's projects; omit it "
            "to use the first project."
        )
    if mode == "header":
        return (
            f"{common} Pass owner_id for compatibility (the server uses X-Owner-Id). "
            "Set metadata.created_by and metadata.updated_by for attribution."
        )
    return (
        f"{common} Always pass owner_id explicitly on reads and writes "
        "(alphanumeric, _, -, @). Set metadata.created_by and "
        "metadata.updated_by for attribution."
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
        configure_owner_scope(server_config.owner_scope)
        if server_config.owner_scope == "token":
            validate_token_mode(
                admin_token=server_config.admin_token,
                keys_file=server_config.api_keys_file,
            )
        self.db_client = open_store(server_config)
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
                backend=server_config.embedding_backend,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to load embeddings model: %s", exc)
            self.embedding_service = _UnavailableEmbeddingService()

        self.db_client.set_embedding_service(self.embedding_service)

        self.mcp = FastMCP(
            name=self.server_config.description or self.server_config.name,
            instructions=self._instructions(),
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
        if not getattr(app.state, "_owner_scope_wrapped", False):
            if self.server_config.owner_scope == "token":
                app.add_middleware(
                    OwnerTokenMiddleware,
                    keys_file=self.server_config.api_keys_file,
                )
            elif self.server_config.owner_scope == "header":
                app.add_middleware(
                    OwnerHeaderMiddleware,
                    admin_token=self.server_config.admin_token,
                )
            app.state._owner_scope_wrapped = True

        from starlette.routing import Route

        from graph_memory_mcp.metrics import metrics_response

        db = self.db_client
        app.router.routes.append(
            Route("/metrics", lambda request: metrics_response(db), methods=["GET"])
        )
        for route in self._admin_routes():
            app.router.routes.append(route)
        for route in self._internal_routes():
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

    def _instructions(self) -> str:
        """MCP connect text. The auth entry overrides this."""
        return _mcp_instructions(self.server_config.owner_scope)

    def _tool_owner_default(self) -> str:
        """Empty in token mode so an omitted owner_id uses the key's first project."""
        if self.server_config.owner_scope == "token":
            return ""
        return self.config.default_owner_id

    def _attribution_tool_help(self, *, source: str | None = "metadata") -> str:
        if self.server_config.owner_scope == "token":
            return (
                "created_by and updated_by are the API key name. "
                "created_at and updated_at are set by the server."
            )
        if source is None:
            return "created_at and updated_at are set by the server."
        return (
            f"created_by and updated_by come from `{source}.created_by` and "
            f"`{source}.updated_by` when those keys are set. "
            "created_at and updated_at are set by the server."
        )

    def _owner_tool_help(self) -> str:
        if self.server_config.owner_scope == "token":
            return (
                "`owner_id` must be one of the API key's projects; omit it to use "
                "the first project."
            )
        if self.server_config.owner_scope == "header":
            return "`owner_id` is ignored; the server uses the X-Owner-Id header."
        return "Pass `owner_id` on every call."

    def _register_tools(self) -> None:
        """Register all MCP tools. To be overridden by subclasses."""
        raise NotImplementedError("Subclasses must implement _register_tools()")

    def _admin_routes(self) -> list:
        """Operator HTTP endpoints (curl-friendly), separate from agent MCP tools.

        ``client`` and ``header`` are open when ``ADMIN_TOKEN`` is empty.
        ``token`` always requires it: these routes take the owner from the path.
        """
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        from graph_memory_mcp.graph_memory import mcp_handlers_admin

        db = self.db_client
        embedding_service = self.embedding_service
        admin_token = self.server_config.admin_token
        keys_file = self.server_config.api_keys_file
        scope = self.server_config.owner_scope

        def _unauthorized(request) -> JSONResponse | None:
            decision = authenticate(
                scope,
                "admin",
                request.headers.get("authorization"),
                admin_token=admin_token,
                keys_file=keys_file,
            )
            if decision.ok:
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
                    preserve_audit=True,
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

    def _internal_routes(self) -> list:
        """Gateway-only calls. Not MCP tools, not published to agents.

        There is no owner query parameter. ``token`` takes the owner from the
        API key. ``client`` and ``header`` require ``ADMIN_TOKEN`` and then
        ``X-Owner-Id``.
        """
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        from graph_memory_mcp.graph_memory.owner_scope import (
            GraphSizeDenied,
            graph_size_owner,
            graph_size_payload,
        )

        db = self.db_client
        cfg = self.server_config

        async def graph_size(request):
            try:
                owner_id = graph_size_owner(
                    scope=cfg.owner_scope,
                    authorization=request.headers.get("authorization"),
                    owner_header=request.headers.get("x-owner-id"),
                    admin_token=cfg.admin_token,
                    keys_file=cfg.api_keys_file,
                )
            except GraphSizeDenied as exc:
                return JSONResponse(
                    {"success": False, "error": str(exc)}, status_code=exc.status
                )
            except ValueError as exc:
                return JSONResponse(
                    {"success": False, "error": str(exc)}, status_code=400
                )
            return JSONResponse(graph_size_payload(db, owner_id))

        return [Route("/internal/graph-size", graph_size, methods=["GET"])]
