"""OWNER_SCOPE does not need FalkorDB: it only decides which string is the owner."""

import asyncio
import logging

import pytest

from graph_memory_mcp.graph_memory.api_keys import create_key, revoke_key
from graph_memory_mcp.graph_memory.owner_scope import (
    GraphSizeDenied,
    HeaderModeConfigError,
    OwnerHeaderMiddleware,
    OwnerTokenMiddleware,
    ProjectDenied,
    bind_api_key,
    bind_mcp_http_request,
    configure_owner_scope,
    graph_size_owner,
    graph_size_payload,
    owner_scope,
    validate_header_bind,
)
from graph_memory_mcp.graph_memory.utils import normalize_owner_id


@pytest.fixture(autouse=True)
def _reset_scope():
    configure_owner_scope("client")
    yield
    configure_owner_scope("client")


def test_client_scope_keeps_the_tool_argument_even_with_a_header():
    configure_owner_scope("client")
    with bind_mcp_http_request("tenant_a"):
        assert normalize_owner_id("other") == "other"


def test_header_scope_ignores_the_tool_argument():
    configure_owner_scope("header")
    with bind_mcp_http_request("tenant_a"):
        assert normalize_owner_id("other") == "tenant_a"
        assert normalize_owner_id("") == "tenant_a"
        assert normalize_owner_id(None) == "tenant_a"


def test_header_scope_rejects_a_missing_header():
    configure_owner_scope("header")
    with bind_mcp_http_request(None):
        with pytest.raises(ValueError, match="X-Owner-Id"):
            normalize_owner_id("other")
    with bind_mcp_http_request("  "):
        with pytest.raises(ValueError, match="X-Owner-Id"):
            normalize_owner_id("other")


def test_header_scope_outside_http_keeps_the_argument():
    """Jobs call handlers in-process. They must not require the gateway header."""
    configure_owner_scope("header")
    assert owner_scope() == "header"
    assert normalize_owner_id("jobs_owner") == "jobs_owner"


def test_header_is_visible_in_a_child_task():
    configure_owner_scope("header")

    async def _run():
        with bind_mcp_http_request("tenant_a"):

            async def child():
                return normalize_owner_id("victim")

            return await asyncio.create_task(child())

    assert asyncio.run(_run()) == "tenant_a"


def test_middleware_binds_only_the_mcp_path():
    configure_owner_scope("header")
    seen = {}

    async def app(scope, receive, send):
        try:
            seen["owner"] = normalize_owner_id("from-tool")
        except ValueError as exc:
            seen["error"] = str(exc)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = OwnerHeaderMiddleware(app)

    async def _call(path, header):
        seen.clear()
        headers = []
        if header is not None:
            headers.append((b"x-owner-id", header.encode()))

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            return None

        await middleware(
            {"type": "http", "path": path, "headers": headers}, receive, send
        )

    asyncio.run(_call("/mcp", "tenant_a"))
    assert seen["owner"] == "tenant_a"

    asyncio.run(_call("/internal/graph-size", "tenant_a"))
    assert seen["owner"] == "from-tool"

    asyncio.run(_call("/mcp", None))
    assert "X-Owner-Id" in seen["error"]


def test_header_middleware_requires_admin_token_when_set():
    configure_owner_scope("header")
    seen = {}

    async def app(scope, receive, send):
        try:
            seen["owner"] = normalize_owner_id("from-tool")
        except ValueError as exc:
            seen["error"] = str(exc)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = OwnerHeaderMiddleware(app, admin_token="secret")

    async def _call(path, authorization):
        seen.clear()
        sent = []
        headers = [(b"x-owner-id", b"tenant_a")]
        if authorization is not None:
            headers.append((b"authorization", authorization.encode()))

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await middleware(
            {"type": "http", "path": path, "headers": headers}, receive, send
        )
        return sent

    sent = asyncio.run(_call("/mcp", None))
    assert "owner" not in seen
    assert sent[0]["status"] == 401

    sent = asyncio.run(_call("/mcp", "Bearer wrong"))
    assert "owner" not in seen
    assert sent[0]["status"] == 401

    sent = asyncio.run(_call("/mcp", "Bearer secret"))
    assert seen["owner"] == "tenant_a"
    assert sent[0]["status"] == 200

    sent = asyncio.run(_call("/internal/graph-size", None))
    assert seen["owner"] == "from-tool"
    assert sent[0]["status"] == 200


def test_token_scope_uses_the_key_projects(tmp_path):
    configure_owner_scope("token")
    record, _raw = create_key(tmp_path / "keys.json", "alice", ["p1", "p2"])
    with bind_api_key(record):
        assert normalize_owner_id("p2") == "p2"
        assert normalize_owner_id(None) == "p1"
        assert normalize_owner_id("") == "p1"
        with pytest.raises(ProjectDenied) as denied:
            normalize_owner_id("bob")
        assert denied.value.status == 403


def test_token_scope_outside_http_keeps_the_argument():
    configure_owner_scope("token")
    assert normalize_owner_id("jobs_owner") == "jobs_owner"


def test_token_middleware_requires_a_live_key(tmp_path):
    configure_owner_scope("token")
    path = tmp_path / "keys.json"
    _record, raw = create_key(path, "alice", ["p1", "p2"])
    seen = {}
    sent = []

    async def app(scope, receive, send):
        try:
            seen["owner"] = normalize_owner_id("bob")
        except ProjectDenied as exc:
            seen["denied"] = exc.status
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = OwnerTokenMiddleware(app, str(path))

    async def _call(path_name, authorization):
        seen.clear()
        sent.clear()
        headers = []
        if authorization is not None:
            headers.append((b"authorization", authorization.encode()))

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await middleware(
            {"type": "http", "path": path_name, "headers": headers},
            receive,
            send,
        )

    asyncio.run(_call("/mcp", None))
    assert "owner" not in seen
    assert sent[0]["status"] == 401

    asyncio.run(_call("/mcp", "Bearer not-a-key"))
    assert "owner" not in seen
    assert sent[0]["status"] == 401

    asyncio.run(_call("/mcp", f"Bearer {raw}"))
    assert "owner" not in seen
    assert seen["denied"] == 403

    asyncio.run(_call("/admin/health", None))
    assert seen["owner"] == "bob"


def test_token_middleware_rejects_a_revoked_key(tmp_path):
    configure_owner_scope("token")
    path = tmp_path / "keys.json"
    record, raw = create_key(path, "alice", ["p1"])
    revoke_key(path, record.id)
    called = {}

    async def app(scope, receive, send):
        called["yes"] = True
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = OwnerTokenMiddleware(app, str(path))

    async def _call():
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await middleware(
            {
                "type": "http",
                "path": "/mcp",
                "headers": [(b"authorization", f"Bearer {raw}".encode())],
            },
            receive,
            send,
        )
        return sent

    sent = asyncio.run(_call())
    assert "yes" not in called
    assert sent[0]["status"] == 401


def test_graph_size_is_closed(tmp_path):
    path = tmp_path / "keys.json"
    _record, raw = create_key(path, "alice", ["alice"])

    with pytest.raises(GraphSizeDenied) as denied:
        graph_size_owner(
            scope="client",
            authorization=None,
            owner_header="alice",
            admin_token="",
            keys_file=str(path),
        )
    assert denied.value.status == 401
    assert (
        graph_size_owner(
            scope="client",
            authorization="Bearer secret",
            owner_header="alice",
            admin_token="secret",
            keys_file=str(path),
        )
        == "alice"
    )

    with pytest.raises(GraphSizeDenied) as header_closed:
        graph_size_owner(
            scope="header",
            authorization=None,
            owner_header="alice",
            admin_token="",
            keys_file=str(path),
        )
    assert header_closed.value.status == 401

    with pytest.raises(GraphSizeDenied) as header_denied:
        graph_size_owner(
            scope="header",
            authorization=None,
            owner_header="alice",
            admin_token="secret",
            keys_file=str(path),
        )
    assert header_denied.value.status == 401

    assert (
        graph_size_owner(
            scope="header",
            authorization="Bearer secret",
            owner_header="alice",
            admin_token="secret",
            keys_file=str(path),
        )
        == "alice"
    )

    with pytest.raises(GraphSizeDenied) as missing:
        graph_size_owner(
            scope="header",
            authorization="Bearer secret",
            owner_header=None,
            admin_token="secret",
            keys_file=str(path),
        )
    assert missing.value.status == 400

    assert (
        graph_size_owner(
            scope="token",
            authorization=f"Bearer {raw}",
            owner_header=None,
            admin_token="",
            keys_file=str(path),
        )
        == "alice"
    )

    with pytest.raises(GraphSizeDenied) as foreign:
        graph_size_owner(
            scope="token",
            authorization=f"Bearer {raw}",
            owner_header="bob",
            admin_token="",
            keys_file=str(path),
        )
    assert foreign.value.status == 403

    with pytest.raises(GraphSizeDenied) as token_denied:
        graph_size_owner(
            scope="token",
            authorization=None,
            owner_header="alice",
            admin_token="secret",
            keys_file=str(path),
        )
    assert token_denied.value.status == 401


def test_header_bind_allows_loopback_and_refuses_the_network(caplog):
    for host in ("127.0.0.1", "::1", "localhost", "LocalHost"):
        validate_header_bind(scope="header", admin_token="", host=host)
    validate_header_bind(scope="header", admin_token="secret", host="0.0.0.0")
    validate_header_bind(scope="token", admin_token="", host="0.0.0.0")
    assert not caplog.records

    with pytest.raises(HeaderModeConfigError, match="X-Owner-Id") as refused:
        validate_header_bind(scope="header", admin_token="", host="0.0.0.0")
    message = str(refused.value)
    assert "ADMIN_TOKEN" in message
    assert "127.0.0.1" in message
    assert "impersonate any owner" in message

    with pytest.raises(HeaderModeConfigError):
        validate_header_bind(scope="header", admin_token="  ", host="::")

    with caplog.at_level(logging.WARNING):
        validate_header_bind(
            scope="header",
            admin_token="",
            host="0.0.0.0",
            allow_insecure=True,
        )
    assert any("X-Owner-Id" in record.message for record in caplog.records)
    assert any("starting anyway" in record.message for record in caplog.records)


def test_cli_refuses_header_mode_on_a_reachable_host(monkeypatch):
    from graph_memory_mcp.cli import main

    monkeypatch.setenv("OWNER_SCOPE", "header")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    monkeypatch.delenv("ALLOW_INSECURE_HEADER", raising=False)
    with pytest.raises(SystemExit) as exc:
        main(["--host", "0.0.0.0"])
    message = str(exc.value)
    assert "X-Owner-Id" in message
    assert "ADMIN_TOKEN" in message
    assert "127.0.0.1" in message


def _patch_server_start(monkeypatch, started):
    import uvicorn

    class _Server:
        def __init__(self, config):
            started["scope"] = config.owner_scope

        def get_mcp_app(self):
            return "app"

    monkeypatch.setattr("graph_memory_mcp.server.GraphMemoryMCP", _Server)

    def _run(app, **kwargs):
        started["app"] = app
        started["host"] = kwargs.get("host")

    monkeypatch.setattr(uvicorn, "run", _run)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "[::]"])
def test_client_mode_refuses_a_non_loopback_bind(host):
    with pytest.raises(HeaderModeConfigError, match="OWNER_SCOPE=client"):
        validate_header_bind(scope="client", admin_token="", host=host)
    # ADMIN_TOKEN does not protect /mcp in client mode.
    with pytest.raises(HeaderModeConfigError, match="ALLOW_INSECURE_CLIENT|token"):
        validate_header_bind(scope="client", admin_token="secret", host=host)


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "127.0.0.2", "::1", "[::1]", "localhost"]
)
def test_client_mode_loopback_bind_starts(host):
    validate_header_bind(scope="client", admin_token="", host=host)


def test_client_mode_opt_in_warns_and_starts(caplog):
    with caplog.at_level(logging.WARNING):
        validate_header_bind(
            scope="client",
            admin_token="",
            host="0.0.0.0",
            allow_insecure_client=True,
        )
    assert any("ALLOW_INSECURE_CLIENT=1" in r.message for r in caplog.records)


def test_cli_refuses_client_mode_on_a_reachable_host(monkeypatch):
    from graph_memory_mcp.cli import main

    monkeypatch.setenv("OWNER_SCOPE", "client")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    monkeypatch.delenv("ALLOW_INSECURE_CLIENT", raising=False)
    started = {}
    _patch_server_start(monkeypatch, started)
    with pytest.raises(SystemExit) as exc:
        main(["--host", "0.0.0.0"])
    assert "OWNER_SCOPE=client" in str(exc.value)
    assert started == {}


def test_cli_client_mode_opt_in_starts_on_any_host(monkeypatch, caplog):
    from graph_memory_mcp.cli import main

    monkeypatch.setenv("OWNER_SCOPE", "client")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    monkeypatch.setenv("ALLOW_INSECURE_CLIENT", "1")
    started = {}
    _patch_server_start(monkeypatch, started)
    with caplog.at_level(logging.WARNING):
        main(["--host", "0.0.0.0"])
    assert started == {"scope": "client", "app": "app", "host": "0.0.0.0"}
    assert any("ALLOW_INSECURE_CLIENT=1" in r.message for r in caplog.records)


def test_cli_client_mode_loopback_starts_without_a_warning(monkeypatch, caplog):
    from graph_memory_mcp.cli import main

    monkeypatch.setenv("OWNER_SCOPE", "client")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    monkeypatch.delenv("ALLOW_INSECURE_CLIENT", raising=False)
    started = {}
    _patch_server_start(monkeypatch, started)
    with caplog.at_level(logging.DEBUG):
        main(["--host", "127.0.0.1"])
    assert started == {"scope": "client", "app": "app", "host": "127.0.0.1"}
    assert not any("OWNER_SCOPE=client" in r.message for r in caplog.records)


def test_cli_header_loopback_without_token_stays_quiet(monkeypatch, caplog):
    from graph_memory_mcp.cli import main

    monkeypatch.setenv("OWNER_SCOPE", "header")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    monkeypatch.delenv("ALLOW_INSECURE_HEADER", raising=False)
    started = {}
    _patch_server_start(monkeypatch, started)
    with caplog.at_level(logging.DEBUG):
        main(["--host", "127.0.0.1"])
    assert started["scope"] == "header"
    assert started["host"] == "127.0.0.1"
    assert not any("X-Owner-Id" in record.message for record in caplog.records)


def test_cli_allow_insecure_header_warns_and_starts(monkeypatch, caplog):
    from graph_memory_mcp.cli import main

    monkeypatch.setenv("OWNER_SCOPE", "header")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    monkeypatch.setenv("ALLOW_INSECURE_HEADER", "1")
    started = {}
    _patch_server_start(monkeypatch, started)
    with caplog.at_level(logging.WARNING):
        main(["--host", "0.0.0.0"])
    assert started["host"] == "0.0.0.0"
    assert any("impersonate any owner" in record.message for record in caplog.records)


def test_graph_size_payload_counts_labels():
    class _DB:
        def graph_size_rows(self, owner_id):
            assert owner_id == "tenant_a"
            return [["Fact", 2], ["Entity", 1]]

        def relation_count(self, owner_id):
            return [[4]]

        def graph_memory_bytes(self, owner_id):
            return 100

    payload = graph_size_payload(_DB(), "tenant_a")
    assert payload["node_count"] == 3
    assert payload["relation_count"] == 4
    assert payload["bytes"] == 100
    assert payload["nodes"] == {"Fact": 2, "Entity": 1}


def _host_app(peer):
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from graph_memory_mcp.graph_memory.owner_scope import LoopbackPeerMiddleware

    inner = Starlette(
        routes=[
            Route("/mcp", lambda r: PlainTextResponse("ok"), methods=["POST"]),
            Route("/metrics", lambda r: PlainTextResponse("ok")),
        ]
    )
    app = LoopbackPeerMiddleware(inner)

    async def with_peer(scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope, client=(peer, 50123))
        await app(scope, receive, send)

    return with_peer


async def _status(app, host, path="/mcp", method="POST"):
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://srv"
    ) as client:
        response = await client.request(method, path, headers={"Host": host})
        return response.status_code


@pytest.mark.parametrize(
    "host", ["127.0.0.1:8000", "localhost:8000", "[::1]:8000", "127.0.0.1"]
)
def test_loopback_host_from_lan_peer_is_rejected(host):
    assert asyncio.run(_status(_host_app("192.168.68.20"), host)) == 421
    assert asyncio.run(_status(_host_app("2001:db8::5"), host)) == 421


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1", "testclient"])
def test_loopback_host_from_loopback_peer_passes(peer):
    assert asyncio.run(_status(_host_app(peer), "127.0.0.1:8000")) == 200


def test_loopback_peer_check_only_covers_mcp():
    app = _host_app("192.168.68.20")
    assert asyncio.run(_status(app, "127.0.0.1:8000", "/metrics", "GET")) == 200


def test_loopback_peer_check_applies_where_mcp_is_open():
    from graph_memory_mcp.graph_memory.owner_scope import needs_loopback_peer_check

    assert needs_loopback_peer_check(scope="client", admin_token="")
    assert needs_loopback_peer_check(scope="client", admin_token="secret")
    assert not needs_loopback_peer_check(
        scope="client", admin_token="", allow_insecure_client=True
    )
    assert needs_loopback_peer_check(scope="header", admin_token="")
    assert not needs_loopback_peer_check(scope="header", admin_token="secret")
    assert not needs_loopback_peer_check(
        scope="header", admin_token="", allow_insecure_header=True
    )
    assert not needs_loopback_peer_check(scope="token", admin_token="secret")


def test_client_mode_app_rejects_spoofed_loopback_host(memory_backend):
    """GMMCP-18: Host 127.0.0.1 from a LAN peer does not reach /mcp."""
    import httpx

    from graph_memory_mcp.server import GraphMemoryMCP

    cfg = memory_backend.config.model_copy(
        update={"owner_scope": "client", "allow_insecure_client": False}
    )
    server = GraphMemoryMCP(cfg)
    app = server.get_mcp_app()

    async def statuses():
        out = []
        async with server.mcp.session_manager.run():
            for peer in ("192.168.68.20", "127.0.0.1"):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app, client=(peer, 50123)),
                    base_url="http://127.0.0.1:8000",
                ) as client:
                    response = await client.post("/mcp", json={})
                    out.append(response.status_code)
        return out

    lan, local = asyncio.run(statuses())
    assert lan == 421
    assert local != 421
