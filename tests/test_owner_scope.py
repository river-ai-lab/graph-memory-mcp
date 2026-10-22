"""OWNER_SCOPE does not need FalkorDB: it only decides which string is the owner."""

import asyncio

import pytest

from graph_memory_mcp.graph_memory.api_keys import create_key, revoke_key
from graph_memory_mcp.graph_memory.owner_scope import (
    GraphSizeDenied,
    OwnerHeaderMiddleware,
    OwnerTokenMiddleware,
    bind_mcp_http_request,
    configure_owner_scope,
    graph_size_owner,
    graph_size_payload,
    owner_scope,
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


def test_token_scope_ignores_the_tool_argument():
    configure_owner_scope("token")
    with bind_mcp_http_request("alice"):
        assert normalize_owner_id("bob") == "alice"
        assert normalize_owner_id(None) == "alice"


def test_token_scope_outside_http_keeps_the_argument():
    configure_owner_scope("token")
    assert normalize_owner_id("jobs_owner") == "jobs_owner"


def test_token_middleware_requires_a_live_key(tmp_path):
    configure_owner_scope("token")
    path = tmp_path / "keys.json"
    _record, raw = create_key(path, "alice")
    seen = {}
    sent = []

    async def app(scope, receive, send):
        seen["owner"] = normalize_owner_id("bob")
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
    assert seen["owner"] == "alice"

    asyncio.run(_call("/admin/health", None))
    assert seen["owner"] == "bob"


def test_token_middleware_rejects_a_revoked_key(tmp_path):
    configure_owner_scope("token")
    path = tmp_path / "keys.json"
    record, raw = create_key(path, "alice")
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
    _record, raw = create_key(path, "alice")

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
            owner_header="bob",
            admin_token="",
            keys_file=str(path),
        )
        == "alice"
    )

    with pytest.raises(GraphSizeDenied) as token_denied:
        graph_size_owner(
            scope="token",
            authorization=None,
            owner_header="alice",
            admin_token="secret",
            keys_file=str(path),
        )
    assert token_denied.value.status == 401


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
