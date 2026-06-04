from __future__ import annotations

import argparse
import logging
import os


def main() -> None:
    default_mcp_url = os.environ.get(
        "GRAPH_MEMORY_MCP_URL", "http://127.0.0.1:8000/mcp"
    )
    parser = argparse.ArgumentParser(
        prog="graph-memory-explorer",
        description=(
            "Local web GUI to explore Graph Memory (read-only). "
            "Requires graph-memory-mcp running separately."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument(
        "--mcp-url",
        default=default_mcp_url,
        help=f"MCP streamable HTTP endpoint (default: {default_mcp_url})",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
    )
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level))

    from graph_memory_mcp.explorer.app import create_app
    from graph_memory_mcp.explorer.mcp_client import McpHttpClient

    mcp_client = McpHttpClient(args.mcp_url)
    app = create_app(mcp_client)

    try:
        import uvicorn
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "uvicorn is required. Install with: pip install uvicorn"
        ) from exc

    print(f"Graph Memory Explorer: http://{args.host}:{args.port}/")
    print(f"MCP backend: {args.mcp_url}")
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
