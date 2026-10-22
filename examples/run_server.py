"""Default-profile MCP server at http://127.0.0.1:8000/mcp."""

import uvicorn

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.server import GraphMemoryMCP


def create_app():
    from graph_memory_mcp.graph_memory.api_keys import TokenModeConfigError

    config = load_mcp_server_config()
    try:
        mcp_server = GraphMemoryMCP(config)
    except TokenModeConfigError as exc:
        raise SystemExit(str(exc)) from exc
    return mcp_server.get_mcp_app()


if __name__ == "__main__":
    print("Starting MCP server...")
    print("MCP Endpoint: http://127.0.0.1:8000/mcp")
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
