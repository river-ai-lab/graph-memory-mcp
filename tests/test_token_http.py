"""Token mode through the real Starlette routes, not the middleware alone."""

from types import SimpleNamespace

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from graph_memory_mcp.base_server import BaseGraphMemoryMCP
from graph_memory_mcp.graph_memory.api_keys import create_key
from graph_memory_mcp.graph_memory.owner_scope import (
    OwnerTokenMiddleware,
    ProjectDenied,
    configure_owner_scope,
)
from graph_memory_mcp.graph_memory.utils import normalize_owner_id


class _DB:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def list_owners(self):
        return ["bob"]

    def delete_owner_graph(self, owner_id):
        self.deleted.append(owner_id)
        return True

    def graph_size_rows(self, owner_id):
        return [["Fact", 1]]

    def relation_count(self, owner_id):
        return [[0]]


def _app(tmp_path, *, scope: str, admin_token: str, keys_file: str):
    db = _DB()

    async def mcp(request):
        configure_owner_scope(scope)
        try:
            owner = normalize_owner_id(request.query_params.get("owner") or "")
        except ProjectDenied as exc:
            return JSONResponse(
                {"success": False, "error": str(exc)}, status_code=exc.status
            )
        return JSONResponse({"owner": owner})

    stub = SimpleNamespace(
        server_config=SimpleNamespace(
            owner_scope=scope,
            admin_token=admin_token,
            api_keys_file=keys_file,
        ),
        db_client=db,
        embedding_service=None,
    )
    routes = [Route("/mcp", mcp, methods=["POST"])]
    routes.extend(BaseGraphMemoryMCP._admin_routes(stub))
    routes.extend(BaseGraphMemoryMCP._internal_routes(stub))
    app = Starlette(routes=routes)
    if scope == "token":
        app.add_middleware(OwnerTokenMiddleware, keys_file=keys_file)
    return app, db


def test_token_routes_require_keys_and_admin_token(tmp_path):
    path = tmp_path / "keys.json"
    _record, raw = create_key(path, "alice", ["p1", "p2"])
    app, db = _app(tmp_path, scope="token", admin_token="", keys_file=str(path))
    client = TestClient(app)

    missing = client.post("/mcp")
    assert missing.status_code == 401

    authed = client.post("/mcp", headers={"Authorization": f"Bearer {raw}"})
    assert authed.status_code == 200
    assert authed.json()["owner"] == "p1"

    picked = client.post("/mcp?owner=p2", headers={"Authorization": f"Bearer {raw}"})
    assert picked.status_code == 200
    assert picked.json()["owner"] == "p2"

    foreign = client.post("/mcp?owner=bob", headers={"Authorization": f"Bearer {raw}"})
    assert foreign.status_code == 403

    blocked = client.delete("/admin/owners/bob")
    assert blocked.status_code == 401
    assert db.deleted == []

    sized = client.get(
        "/internal/graph-size",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert sized.status_code == 200
    assert sized.json()["owner_id"] == "p1"

    foreign_size = client.get(
        "/internal/graph-size",
        headers={"Authorization": f"Bearer {raw}", "X-Owner-Id": "bob"},
    )
    assert foreign_size.status_code == 403


def test_token_admin_accepts_the_admin_token(tmp_path):
    path = tmp_path / "keys.json"
    create_key(path, "alice", ["p1"])
    app, db = _app(tmp_path, scope="token", admin_token="secret", keys_file=str(path))
    client = TestClient(app)

    denied = client.delete(
        "/admin/owners/bob", headers={"Authorization": "Bearer other"}
    )
    assert denied.status_code == 401
    assert db.deleted == []

    allowed = client.delete(
        "/admin/owners/bob", headers={"Authorization": "Bearer secret"}
    )
    assert allowed.status_code == 200
    assert db.deleted == ["bob"]


def test_header_graph_size_stays_open_for_the_gateway(tmp_path):
    app, _db = _app(tmp_path, scope="header", admin_token="", keys_file="")
    client = TestClient(app)
    response = client.get("/internal/graph-size", headers={"X-Owner-Id": "alice"})
    assert response.status_code == 200
    assert response.json()["owner_id"] == "alice"
