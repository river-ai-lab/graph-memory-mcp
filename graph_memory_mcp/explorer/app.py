"""Starlette app: static explorer UI + read-only MCP tool proxy."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from graph_memory_mcp.explorer.mcp_client import McpToolClient

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

READ_ONLY_TOOLS = frozenset(
    {
        "health_check",
        "test_connection",
        "get_stats",
        "get_node",
        "get_context",
        "get_trace",
        "find_similar",
        "search",
        "search_triplets",
        "get_node_change_history",
    }
)


def create_app(mcp_client: McpToolClient) -> Starlette:
    @asynccontextmanager
    async def lifespan(app: Starlette):
        try:
            await mcp_client.connect()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not connect to MCP at %s: %s", mcp_client.url, exc)
        yield
        await mcp_client.close()

    async def index(_request: Request) -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    async def health(_request: Request) -> JSONResponse:
        payload: dict[str, Any] = {
            "ready": False,
            "mcp_url": mcp_client.url,
        }
        if not mcp_client.connected:
            payload["error"] = "MCP server not connected"
            return JSONResponse(payload)

        try:
            health_result = await mcp_client.call_tool("health_check", {})
            payload["health"] = health_result
            payload["ready"] = bool(health_result.get("success"))
        except Exception as exc:  # noqa: BLE001
            payload["health_error"] = str(exc)
        return JSONResponse(payload)

    async def list_tools(_request: Request) -> JSONResponse:
        return JSONResponse({"tools": sorted(READ_ONLY_TOOLS)})

    async def call_tool(request: Request) -> JSONResponse:
        if not mcp_client.connected:
            return JSONResponse(
                {
                    "success": False,
                    "error": (
                        f"MCP server not connected ({mcp_client.url}). "
                        "Start graph-memory-mcp first."
                    ),
                },
                status_code=503,
            )

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse(
                {"success": False, "error": "Invalid JSON body"}, status_code=400
            )

        tool = body.get("tool")
        arguments = body.get("arguments") or {}
        if not isinstance(tool, str) or not tool:
            return JSONResponse(
                {"success": False, "error": "Missing tool name"}, status_code=400
            )
        if not isinstance(arguments, dict):
            return JSONResponse(
                {"success": False, "error": "arguments must be an object"},
                status_code=400,
            )
        if tool not in READ_ONLY_TOOLS:
            return JSONResponse(
                {"success": False, "error": f"Tool not allowed: {tool}"},
                status_code=403,
            )

        try:
            result = await mcp_client.call_tool(tool, arguments)
        except TypeError as exc:
            return JSONResponse(
                {"success": False, "error": f"Bad arguments: {exc}"},
                status_code=400,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Tool %s failed", tool)
            return JSONResponse(
                {"success": False, "error": str(exc)},
                status_code=500,
            )

        return JSONResponse(result)

    routes = [
        Route("/", index),
        Route("/health", health),
        Route("/api/tools", list_tools),
        Route("/api/tool", call_tool, methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    ]
    return Starlette(routes=routes, lifespan=lifespan)
