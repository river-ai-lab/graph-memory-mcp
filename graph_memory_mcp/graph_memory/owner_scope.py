"""Who chooses owner_id on an MCP HTTP call.

`client` (default): the tool argument, as in a trusted local or company
    deploy.
`header`: the tool argument is ignored. The owner is `X-Owner-Id`, set by
    an authenticating gateway in front of the server.
`token`: the tool argument is ignored. The owner is the one stored for the
    ``Authorization: Bearer`` API key. A missing or revoked key is HTTP 401.

Jobs and in-process calls are not HTTP requests, so they keep the owner they
were given. Header and token modes bind that owner on the HTTP request task.
FastMCP runs the tool in a child task started after that bind; the child
copies the context.
"""

from __future__ import annotations

import hmac
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from graph_memory_mcp.graph_memory.api_keys import bearer_value, owner_for_bearer

_configured_scope = "client"
_mcp_request: ContextVar[bool] = ContextVar("gm_mcp_request", default=False)
_header_owner: ContextVar[str | None] = ContextVar("gm_header_owner", default=None)

HEADER_NAME = "x-owner-id"
_SCOPES = ("client", "header", "token")


def configure_owner_scope(scope: str) -> None:
    """Set the process mode. Unknown values are rejected."""
    global _configured_scope
    value = str(scope or "client").strip().lower()
    if value not in _SCOPES:
        raise ValueError(
            f"Unknown OWNER_SCOPE {scope!r}. Supported: client, header, token."
        )
    _configured_scope = value


def owner_scope() -> str:
    return _configured_scope


def pinned_owner_argument() -> str | None:
    """Owner that replaces the tool argument, or None to keep the argument.

    Raises ValueError when header or token mode is serving an MCP HTTP request
    and no owner was bound. An empty value must not fall back to
    `DEFAULT_OWNER_ID` or to the tool argument. Token mode rejects the request
    in middleware before this runs; the error here is the in-process backstop.
    """
    if _configured_scope not in ("header", "token") or not _mcp_request.get():
        return None
    raw = _header_owner.get()
    if raw is None or not str(raw).strip():
        if _configured_scope == "token":
            raise ValueError("API key is required")
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


class OwnerTokenMiddleware:
    """Require a Bearer API key on ``/mcp`` and bind that key's owner.

    ``/admin`` is unchanged. ``/internal/graph-size`` checks the key itself.
    """

    def __init__(self, app, keys_file: str):
        self.app = app
        self.keys_file = keys_file

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if path != "/mcp" and not path.startswith("/mcp/"):
            await self.app(scope, receive, send)
            return
        authorization = _header_value(scope, "authorization")
        owner = owner_for_bearer(self.keys_file, authorization)
        if not owner:
            await _send_unauthorized(send)
            return
        with bind_mcp_http_request(owner):
            await self.app(scope, receive, send)


class GraphSizeDenied(Exception):
    """``/internal/graph-size`` refused the caller."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def graph_size_owner(
    *,
    scope: str,
    authorization: str | None,
    owner_header: str | None,
    admin_token: str,
    keys_file: str,
) -> str:
    """Owner for ``/internal/graph-size``.

    ``token`` uses the API key and ignores ``X-Owner-Id``. ``client`` and
    ``header`` require ``ADMIN_TOKEN``; the owner is still ``X-Owner-Id``.
    """
    from graph_memory_mcp.graph_memory.utils import normalize_owner_id

    mode = str(scope or "client").strip().lower()
    if mode == "token":
        owner = owner_for_bearer(keys_file, authorization)
        if not owner:
            raise GraphSizeDenied(401, "Unauthorized")
        return normalize_owner_id(owner)
    if not _admin_bearer(authorization, admin_token):
        raise GraphSizeDenied(401, "Unauthorized")
    raw = (owner_header or "").strip()
    if not raw:
        raise GraphSizeDenied(400, "X-Owner-Id header is required")
    return normalize_owner_id(raw)


def _header_from_scope(scope) -> str | None:
    return _header_value(scope, HEADER_NAME)


def _header_value(scope, name: str) -> str | None:
    wanted = name.encode("ascii")
    for header_name, value in scope.get("headers") or []:
        if header_name.lower() == wanted:
            return value.decode("utf-8", errors="replace")
    return None


def _admin_bearer(authorization: str | None, admin_token: str) -> bool:
    presented = bearer_value(authorization)
    if not admin_token or presented is None:
        return False
    return hmac.compare_digest(presented.encode(), admin_token.encode())


async def _send_unauthorized(send) -> None:
    body = b'{"success":false,"error":"Unauthorized"}'
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


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
