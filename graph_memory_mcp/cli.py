from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="graph-memory-mcp",
        description="Run MCP Graph Memory server (FastMCP HTTP).",
    )
    parser.add_argument(
        "--backend",
        default=None,
        help="Graph backend. Supported: arcadedb (default), falkordb. Overrides GRAPH_BACKEND.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
    )
    profile = parser.add_mutually_exclusive_group()
    profile.add_argument(
        "--simple",
        action="store_true",
        help=(
            "Use graph_memory_mcp.server_simple: like the default server but "
            "provenance is flat fields (ref, provenance_type, …) instead of a nested "
            "`source` object."
        ),
    )
    profile.add_argument(
        "--extended",
        action="store_true",
        help=(
            "Use graph_memory_mcp.server_extended: same tools as the default server, "
            "plus description, shared_with_ids, and collection_id on writes."
        ),
    )
    keys = parser.add_subparsers(dest="command")
    keys_parser = keys.add_parser(
        "keys",
        help="Manage API keys for OWNER_SCOPE=token",
    )
    keys_commands = keys_parser.add_subparsers(dest="keys_command", required=True)
    create = keys_commands.add_parser("create", help="Print a new key once")
    create.add_argument("--owner", required=True, help="Owner this key selects")
    create.add_argument(
        "--file",
        default=None,
        help="Keys file. Default is API_KEYS_FILE or keys.json",
    )
    listing = keys_commands.add_parser("list", help="List key ids and owners")
    listing.add_argument("--file", default=None)
    revoke = keys_commands.add_parser("revoke", help="Revoke a key by id")
    revoke.add_argument("key_id")
    revoke.add_argument("--file", default=None)

    args = parser.parse_args(argv)
    if args.command == "keys":
        _keys_command(args)
        return

    logging.basicConfig(level=getattr(logging, args.log_level))

    from graph_memory_mcp.config import load_mcp_server_config

    memory_cfg = load_mcp_server_config()
    if args.backend:
        memory_cfg.graph_backend = args.backend

    from graph_memory_mcp.graph_memory.api_keys import TokenModeConfigError

    try:
        if args.simple:
            from graph_memory_mcp.server_simple import GraphMemorySimpleMCP

            server = GraphMemorySimpleMCP(memory_cfg)
        elif args.extended:
            from graph_memory_mcp.server_extended import GraphMemoryExtendedMCP

            server = GraphMemoryExtendedMCP(memory_cfg)
        else:
            from graph_memory_mcp.server import GraphMemoryMCP

            server = GraphMemoryMCP(memory_cfg)
    except TokenModeConfigError as exc:
        raise SystemExit(str(exc)) from exc
    app = server.get_mcp_app()

    try:
        import uvicorn
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "uvicorn is required to run the HTTP server. Install with: pip install uvicorn"
        ) from exc

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())


def _keys_command(args) -> None:
    from graph_memory_mcp.graph_memory.api_keys import create_key, list_keys, revoke_key

    path = _keys_file(args.file)
    if args.keys_command == "create":
        try:
            record, raw = create_key(path, args.owner)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"id: {record.id}")
        print(f"owner: {record.owner}")
        print(raw)
        return
    if args.keys_command == "list":
        try:
            rows = list_keys(path)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if not rows:
            print("no keys")
            return
        for row in rows:
            state = "revoked" if row.revoked else "active"
            print(f"{row.id}\t{row.owner}\t{row.created_at}\t{state}")
        return
    try:
        record = revoke_key(path, args.key_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if record is None:
        print(f"Unknown key id {args.key_id}", file=sys.stderr)
        raise SystemExit(1)
    print(f"revoked {record.id} ({record.owner})")


def _keys_file(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    from graph_memory_mcp.config import load_mcp_server_config

    return Path(load_mcp_server_config().api_keys_file)


if __name__ == "__main__":
    main()
