from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="graph-memory-mcp",
        description="Run MCP Graph Memory server (streamable HTTP).",
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
            "provenance is flat fields (ref, provenance_type, source_updated_at, …) instead of a nested "
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
    profile.add_argument(
        "--auth",
        action="store_true",
        help=(
            "Use graph_memory_mcp.server_auth: OWNER_SCOPE=token. "
            "Tool schemas omit owner_id; the server sets it from the API key."
        ),
    )
    keys = parser.add_subparsers(dest="command")
    keys_parser = keys.add_parser(
        "keys",
        help="Manage API keys for OWNER_SCOPE=token",
    )
    keys_commands = keys_parser.add_subparsers(dest="keys_command", required=True)
    create = keys_commands.add_parser("create", help="Print a new key once")
    create.add_argument("--name", required=True, help="Person this key identifies")
    create.add_argument(
        "--projects",
        required=True,
        help="Comma-separated owner graphs this key may write",
    )
    create.add_argument(
        "--file",
        default=None,
        help="Keys file. Default is API_KEYS_FILE or keys.json",
    )
    listing = keys_commands.add_parser(
        "list", help="List key ids, names, projects, and created times"
    )
    listing.add_argument("--file", default=None)
    set_projects = keys_commands.add_parser(
        "set-projects", help="Replace the project list for a key"
    )
    set_projects.add_argument("key_id")
    set_projects.add_argument("projects", help="Comma-separated owner graphs")
    set_projects.add_argument("--file", default=None)
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
    if args.auth:
        memory_cfg.owner_scope = "token"

    from graph_memory_mcp.graph_memory.api_keys import TokenModeConfigError
    from graph_memory_mcp.graph_memory.owner_scope import (
        HeaderModeConfigError,
        validate_header_bind,
    )

    try:
        validate_header_bind(
            scope=memory_cfg.owner_scope,
            admin_token=memory_cfg.admin_token,
            host=args.host,
            allow_insecure=memory_cfg.allow_insecure_header,
            allow_insecure_client=memory_cfg.allow_insecure_client,
        )
        if args.simple:
            from graph_memory_mcp.server_simple import GraphMemorySimpleMCP

            server = GraphMemorySimpleMCP(memory_cfg)
        elif args.extended:
            from graph_memory_mcp.server_extended import GraphMemoryExtendedMCP

            server = GraphMemoryExtendedMCP(memory_cfg)
        elif args.auth:
            from graph_memory_mcp.server_auth import GraphMemoryAuthMCP

            server = GraphMemoryAuthMCP(memory_cfg)
        else:
            from graph_memory_mcp.server import GraphMemoryMCP

            server = GraphMemoryMCP(memory_cfg)
    except (TokenModeConfigError, HeaderModeConfigError) as exc:
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
    from graph_memory_mcp.graph_memory.api_keys import (
        create_key,
        list_keys,
        revoke_key,
        set_projects,
    )

    path = _keys_file(args.file)
    if args.keys_command == "create":
        try:
            record, raw = create_key(path, args.name, args.projects)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"id: {record.id}")
        print(f"name: {record.name}")
        print(f"projects: {','.join(record.projects)}")
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
            projects = ",".join(row.projects)
            print(f"{row.id}\t{row.name}\t{projects}\t{row.created_at}\t{state}")
        return
    if args.keys_command == "set-projects":
        try:
            record = set_projects(path, args.key_id, args.projects)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if record is None:
            print(f"Unknown key id {args.key_id}", file=sys.stderr)
            raise SystemExit(1)
        print(f"{record.id}\t{record.name}\t{','.join(record.projects)}")
        return
    try:
        record = revoke_key(path, args.key_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if record is None:
        print(f"Unknown key id {args.key_id}", file=sys.stderr)
        raise SystemExit(1)
    print(f"revoked {record.id} ({record.name})")


def _keys_file(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    from graph_memory_mcp.config import load_mcp_server_config

    return Path(load_mcp_server_config().api_keys_file)


if __name__ == "__main__":
    main()
