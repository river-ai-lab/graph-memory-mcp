from __future__ import annotations

import argparse
import logging


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="graph-memory-mcp",
        description="Run MCP Graph Memory server (FastMCP HTTP).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
    )
    parser.add_argument(
        "--simple",
        action="store_true",
        help=(
            "Use graph_memory_mcp.server_simple: like the default server but "
            "provenance is flat fields (ref, provenance_type, …) instead of a nested "
            "`source` object."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level))

    from graph_memory_mcp.config import load_mcp_server_config

    memory_cfg = load_mcp_server_config()

    if args.simple:
        from graph_memory_mcp.server_simple import GraphMemorySimpleMCP

        server = GraphMemorySimpleMCP(memory_cfg)
    else:
        from graph_memory_mcp.server import GraphMemoryMCP

        server = GraphMemoryMCP(memory_cfg)
    app = server.get_mcp_app()

    try:
        import uvicorn
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "uvicorn is required to run the HTTP server. Install with: pip install uvicorn"
        ) from exc

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
