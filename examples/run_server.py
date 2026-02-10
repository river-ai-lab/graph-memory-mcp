"""
HTTP Server Example
===================

This example runs the Graph Memory MCP server as a standalone HTTP service
using Starlette and Uvicorn.

Usage:
    python examples/run_server.py

This exposes the MCP SSE endpoint at:
    http://127.0.0.1:8000/mcp/sse
"""

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.server import GraphMemoryMCP


async def health(request):
    return JSONResponse({"status": "ok"})


def create_app():
    # 1. Load Config
    config = load_mcp_server_config()

    # 2. Initialize MCP Server
    mcp_server = GraphMemoryMCP(config)

    # 3. Get the MCP ASGI App
    # This app handles /sse (SSE stream) and /messages (POST)
    mcp_app = mcp_server.get_mcp_app()

    # 4. Mount it into your main app
    # We mount it at root "/" so that /sse is accessible at http://.../sse
    # If you mount at "/mcp", then it would be /mcp/sse
    routes = [Route("/health", health), Mount("/mcp", app=mcp_app)]

    return Starlette(routes=routes)


if __name__ == "__main__":
    print("Starting Embedded MCP Server...")
    print("MCP Endpoint: http://127.0.0.1:8000/mcp/sse")
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
