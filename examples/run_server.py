"""Default-profile MCP server at http://127.0.0.1:8000/mcp."""

import uvicorn

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.server import GraphMemoryMCP

_HOST = "127.0.0.1"


def create_app():
    from graph_memory_mcp.graph_memory.api_keys import TokenModeConfigError
    from graph_memory_mcp.graph_memory.owner_scope import (
        HeaderModeConfigError,
        validate_header_bind,
    )

    config = load_mcp_server_config()
    try:
        validate_header_bind(
            scope=config.owner_scope,
            admin_token=config.admin_token,
            host=_HOST,
            allow_insecure=config.allow_insecure_header,
            allow_insecure_client=config.allow_insecure_client,
        )
        mcp_server = GraphMemoryMCP(config)
    except (TokenModeConfigError, HeaderModeConfigError) as exc:
        raise SystemExit(str(exc)) from exc
    return mcp_server.get_mcp_app()


if __name__ == "__main__":
    print("Starting MCP server...")
    print(f"MCP Endpoint: http://{_HOST}:8000/mcp")
    uvicorn.run(create_app(), host=_HOST, port=8000)
