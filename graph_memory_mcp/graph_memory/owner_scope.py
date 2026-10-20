"""Who chooses owner_id on an MCP HTTP call.

`client` (default): the tool argument, as in a trusted local or company
    deploy.
`header`: the tool argument is ignored. The owner is `X-Owner-Id`, set by
    an authenticating gateway in front of the server. Jobs and in-process
    calls are not HTTP requests, so they keep the owner they were given.

The header is bound on the HTTP request task. FastMCP runs the tool in a child
task started after that bind; the child copies the context.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_configured_scope = "client"
_mcp_request: ContextVar[bool] = ContextVar("gm_mcp_request", default=False)
_header_owner: ContextVar[str | None] = ContextVar("gm_header_owner", default=None)

HEADER_NAME = "x-owner-id"


def configure_owner_scope(scope: str) -> None:
    """Set the process mode. Unknown values are rejected."""
    global _configured_scope
    value = str(scope or "client").strip().lower()
    if value not in ("client", "header"):
        raise ValueError(f"Unknown OWNER_SCOPE {scope!r}. Supported: client, header.")
    _configured_scope = value


def owner_scope() -> str:
    return _configured_scope


def pinned_owner_argument() -> str | None:
    """Owner that replaces the tool argument, or None to keep the argument.

    Raises ValueError when header mode is serving an MCP HTTP request and
    `X-Owner-Id` is missing. An empty header must not fall back to
    `DEFAULT_OWNER_ID` or to the tool argument.
    """
    if _configured_scope != "header" or not _mcp_request.get():
        return None
    raw = _header_owner.get()
    if raw is None or not str(raw).strip():
        raise ValueError("X-Owner-Id header is required")
    return str(raw).strip()


@contextmanager
def bind_mcp_http_request(header: str | None) -> Iterator[None]:
    """Mark the current context as an MCP HTTP request carrying this header."""
    token_request = _mcp_request.set(True)
    token_header = _header_owner.set(header)
    try:
        yield
    finally:
        _mcp_request.reset(token_request)
        _header_owner.reset(token_header)


class OwnerHeaderMiddleware:
    """Bind `X-Owner-Id` for `/mcp` only. `/admin` and `/internal` stay separate."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if path != "/mcp" and not path.startswith("/mcp/"):
            await self.app(scope, receive, send)
            return
        header = _header_from_scope(scope)
        with bind_mcp_http_request(header):
            await self.app(scope, receive, send)


def _header_from_scope(scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name.lower() == HEADER_NAME.encode("ascii"):
            return value.decode("utf-8", errors="replace")
    return None


def graph_size_payload(db, owner_id: str) -> dict:
    """Counts the gateway can compare to a storage quota.

    RPM and request totals stay on the gateway. `bytes` is Redis memory of the
    owner graph when the backend can report it, otherwise null.
    """
    nodes: dict[str, int] = {}
    for row in db.graph_size_rows(owner_id):
        if not row or row[0] is None:
            continue
        nodes[str(row[0])] = int(row[1])
    rel_rows = db.relation_count(owner_id)
    relation_count = int(rel_rows[0][0]) if rel_rows else 0
    memory = getattr(db, "graph_memory_bytes", None)
    nbytes = memory(owner_id) if memory is not None else None
    return {
        "success": True,
        "owner_id": owner_id,
        "nodes": nodes,
        "node_count": sum(nodes.values()),
        "relation_count": relation_count,
        "bytes": nbytes,
    }
