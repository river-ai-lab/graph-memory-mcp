"""Default-profile MCP server at http://127.0.0.1:8000/mcp."""

import uvicorn

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.server import GraphMemoryMCP


def create_app():
    config = load_mcp_server_config()
    mcp_server = GraphMemoryMCP(config)
    return mcp_server.get_mcp_app()


if __name__ == "__main__":
    print("Starting MCP server...")
    print("MCP Endpoint: http://127.0.0.1:8000/mcp")
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
