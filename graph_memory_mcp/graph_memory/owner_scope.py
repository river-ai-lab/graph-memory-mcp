"""Who chooses owner_id on an MCP HTTP call.

`client` (default): the tool argument, as in a trusted local or company
    deploy.
`header`: the tool argument is ignored. The owner is `X-Owner-Id`, set by
    a gateway in front of a server bound to loopback. When `ADMIN_TOKEN` is
    set, `/mcp` requires `Authorization: Bearer <ADMIN_TOKEN>`.
`token`: a Bearer API key is required. ``owner_id`` must be one of that
    key's projects; if omitted, the first project is used. ``created_by`` and
    ``updated_by`` are the key's name.

Jobs and in-process calls are not HTTP requests, so they keep the owner they
were given. Header and token modes bind request state on the HTTP request
task. The server runs the tool after the bind. A child task copies the
context, and a synchronous handler's worker thread copies it again.

``_SURFACE_AUTH`` is the only map from mode to credential. ``/mcp``,
``/admin``, and ``/internal/graph-size`` all go through ``authenticate``.
"""

from __future__ import annotations

import ipaddress
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from graph_memory_mcp.graph_memory.api_keys import (
    ApiKeyRecord,
    bearer_matches,
    key_for_bearer,
)

logger = logging.getLogger(__name__)

_configured_scope = "client"
_mcp_request: ContextVar[bool] = ContextVar("gm_mcp_request", default=False)
_header_owner: ContextVar[str | None] = ContextVar("gm_header_owner", default=None)
_bound_key: ContextVar[ApiKeyRecord | None] = ContextVar("gm_bound_key", default=None)

HEADER_NAME = "x-owner-id"
_SCOPES = ("client", "header", "token")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

# Credential for each HTTP surface.
# open: no credential.
# admin: Bearer ADMIN_TOKEN when it is set; open when it is empty.
# admin_required: Bearer ADMIN_TOKEN. Empty or wrong is 401.
# api_key: Bearer API key.
_SURFACE_AUTH: dict[str, dict[str, str]] = {
    "client": {"mcp": "open", "admin": "admin", "graph_size": "admin_required"},
    "header": {"mcp": "admin", "admin": "admin", "graph_size": "admin_required"},
    "token": {"mcp": "api_key", "admin": "admin_required", "graph_size": "api_key"},
}


class HeaderModeConfigError(RuntimeError):
    """An unauthenticated /mcp (client, or header without ADMIN_TOKEN) is
    bound to a non-loopback address."""


class ProjectDenied(Exception):
    """The requested owner_id is not in the API key's projects."""

    def __init__(self, message: str, status: int = 403) -> None:
        super().__init__(message)
        self.status = status


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


@dataclass(frozen=True)
class AuthResult:
    """One authentication check. ``status`` is set when the call is refused."""

    record: ApiKeyRecord | None = None
    status: int | None = None

    @property
    def ok(self) -> bool:
        return self.status is None


def authenticate(
    scope: str,
    surface: str,
    authorization: str | None,
    *,
    admin_token: str,
    keys_file: str,
) -> AuthResult:
    """Apply ``_SURFACE_AUTH`` for this mode and surface.

    API-key surfaces return the live key. Admin-token surfaces use
    ``bearer_matches``. An unknown mode uses the client rules.
    """
    mode = str(scope or "client").strip().lower()
    credential = _SURFACE_AUTH.get(mode, _SURFACE_AUTH["client"])[surface]
    if credential == "open":
        return AuthResult()
    if credential == "api_key":
        record = key_for_bearer(keys_file, authorization)
        if record is None:
            return AuthResult(status=401)
        return AuthResult(record=record)
    if credential == "admin" and not admin_token:
        return AuthResult()
    if bearer_matches(authorization, admin_token):
        return AuthResult()
    return AuthResult(status=401)


def is_loopback_host(host: str) -> bool:
    """True for ``localhost`` and loopback IPs (``127.0.0.0/8``, ``::1``)."""
    value = str(host or "").strip().lower().strip("[]")
    if value in _LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def validate_header_bind(
    *,
    scope: str,
    admin_token: str,
    host: str,
    allow_insecure: bool = False,
    allow_insecure_client: bool = False,
) -> None:
    """Refuse an unauthenticated ``/mcp`` on a non-loopback bind.

    ``header`` without ``ADMIN_TOKEN`` and ``client`` (``/mcp`` never checks a
    credential there) refuse a non-loopback host. Loopback starts quietly.
    ``token`` returns immediately. ``allow_insecure`` is
    ``ALLOW_INSECURE_HEADER=1`` and ``allow_insecure_client`` is
    ``ALLOW_INSECURE_CLIENT=1``: log the risk and continue.
    """
    mode = str(scope or "client").strip().lower()
    if mode not in ("client", "header"):
        return
    if is_loopback_host(host):
        return
    if mode == "client":
        message = (
            f"OWNER_SCOPE=client is bound to {host}. /mcp has no authentication "
            "in this mode: anyone on the network can read, write, and delete "
            "any owner's memory. Bind 127.0.0.1 or use OWNER_SCOPE=token."
        )
        if allow_insecure_client:
            logger.warning(
                "%s ALLOW_INSECURE_CLIENT=1 is set; starting anyway.", message
            )
            return
        raise HeaderModeConfigError(message)
    if str(admin_token or "").strip():
        return
    message = (
        f"OWNER_SCOPE=header is bound to {host} without ADMIN_TOKEN. "
        "Anyone on the network can impersonate any owner via X-Owner-Id. "
        "Set ADMIN_TOKEN or bind 127.0.0.1."
    )
    if allow_insecure:
        logger.warning("%s ALLOW_INSECURE_HEADER=1 is set; starting anyway.", message)
        return
    raise HeaderModeConfigError(message)


def _is_remote_ip(peer: str) -> bool:
    """True for a non-loopback IP. Unix sockets and test peers are not IPs."""
    try:
        return not ipaddress.ip_address(str(peer or "")).is_loopback
    except ValueError:
        return False


def _host_name(host_header: str) -> str:
    """Host header without the port: ``[::1]:8000`` -> ``::1``."""
    value = host_header.strip()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    if value.count(":") == 1:
        return value.rsplit(":", 1)[0]
    return value


class LoopbackPeerMiddleware:
    """Reject a loopback ``Host`` on ``/mcp`` from a non-loopback peer (421).

    The SDK Host allowlist only accepts loopback names, but the header is
    client-controlled: a LAN client can send ``Host: 127.0.0.1``. Used where
    ``/mcp`` has no credential. It is not an access-control boundary by
    itself; authentication is (``OWNER_SCOPE=token``).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not str(scope.get("path", "")).startswith(
            "/mcp"
        ):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        peer = client[0] if client else ""
        host = ""
        for key, value in scope.get("headers") or []:
            if key == b"host":
                host = value.decode("latin-1")
                break
        if _is_remote_ip(peer) and is_loopback_host(_host_name(host)):
            from starlette.responses import Response

            await Response("Invalid Host header", status_code=421)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def needs_loopback_peer_check(
    *,
    scope: str,
    admin_token: str,
    allow_insecure_header: bool = False,
    allow_insecure_client: bool = False,
) -> bool:
    """True when ``/mcp`` has no credential and no network opt-in is set."""
    mode = str(scope or "client").strip().lower()
    if mode == "client":
        return not allow_insecure_client
    if mode == "header":
        return not str(admin_token or "").strip() and not allow_insecure_header
    return False


def bound_key() -> ApiKeyRecord | None:
    """API key bound for this MCP HTTP request, if any."""
    return _bound_key.get()


def bound_key_name() -> str | None:
    """Author for token-mode writes: the key's name, or None outside token HTTP."""
    record = _bound_key.get()
    if record is None:
        return None
    name = str(record.name or "").strip()
    return name or None


def pinned_owner_argument() -> str | None:
    """Owner that replaces the tool argument, or None to keep the argument.

    Raises ValueError when header mode is serving an MCP HTTP request and no
    owner was bound. An empty value must not fall back to `DEFAULT_OWNER_ID`
    or to the tool argument. Token mode does not pin: it validates the tool
    argument against the key's projects. A missing key is rejected in
    middleware before this runs.
    """
    if _configured_scope != "header" or not _mcp_request.get():
        return None
    raw = _header_owner.get()
    if raw is None or not str(raw).strip():
        raise ValueError("X-Owner-Id header is required")
    return str(raw).strip()


def resolve_token_owner(requested: str | None) -> str:
    """Pick or reject owner_id for a token-mode MCP HTTP request."""
    record = _bound_key.get()
    if record is None:
        raise ValueError("API key is required")
    if not record.projects:
        raise ProjectDenied("API key has no projects")
    raw = str(requested or "").strip()
    if not raw:
        return str(record.projects[0])
    if raw not in record.projects:
        allowed = ", ".join(record.projects)
        raise ProjectDenied(
            f"owner_id {raw!r} is not in this API key's projects ({allowed})"
        )
    return raw


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


@contextmanager
def bind_api_key(record: ApiKeyRecord) -> Iterator[None]:
    """Bind a live API key for a token-mode MCP HTTP request."""
    token_request = _mcp_request.set(True)
    token_key = _bound_key.set(record)
    try:
        yield
    finally:
        _mcp_request.reset(token_request)
        _bound_key.reset(token_key)


class OwnerHeaderMiddleware:
    """Bind `X-Owner-Id` for `/mcp`. When ADMIN_TOKEN is set, require it first.

    `/admin` and `/internal` authenticate themselves.
    """

    def __init__(self, app, admin_token: str = ""):
        self.app = app
        self.admin_token = admin_token

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if path != "/mcp" and not path.startswith("/mcp/"):
            await self.app(scope, receive, send)
            return
        decision = authenticate(
            "header",
            "mcp",
            _header_value(scope, "authorization"),
            admin_token=self.admin_token,
            keys_file="",
        )
        if not decision.ok:
            await _send_unauthorized(send)
            return
        header = _header_from_scope(scope)
        with bind_mcp_http_request(header):
            await self.app(scope, receive, send)


class OwnerTokenMiddleware:
    """Require a Bearer API key on ``/mcp`` and bind that key.

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
        decision = authenticate(
            "token",
            "mcp",
            _header_value(scope, "authorization"),
            admin_token="",
            keys_file=self.keys_file,
        )
        if decision.record is None:
            await _send_unauthorized(send)
            return
        with bind_api_key(decision.record):
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

    ``token`` uses the API key. ``X-Owner-Id`` must be one of the key's
    projects when sent; if omitted, the first project is used. ``client``
    and ``header`` require ``ADMIN_TOKEN`` and then ``X-Owner-Id``.
    """
    from graph_memory_mcp.graph_memory.utils import (
        normalize_owner_id,
        require_owner_id_format,
    )

    decision = authenticate(
        scope,
        "graph_size",
        authorization,
        admin_token=admin_token,
        keys_file=keys_file,
    )
    if not decision.ok:
        raise GraphSizeDenied(decision.status or 401, "Unauthorized")
    record = decision.record
    if record is not None:
        raw = (owner_header or "").strip()
        if not raw:
            return require_owner_id_format(record.projects[0])
        if raw not in record.projects:
            raise GraphSizeDenied(
                403,
                f"owner_id {raw!r} is not in this API key's projects",
            )
        return require_owner_id_format(raw)
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
