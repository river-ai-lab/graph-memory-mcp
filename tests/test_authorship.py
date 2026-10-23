"""Project-scoped keys plus server-controlled authorship."""

import time
import uuid

import pytest

from graph_memory_mcp.base_server import _mcp_instructions
from graph_memory_mcp.graph_memory import mcp_handlers_admin as admin
from graph_memory_mcp.graph_memory.api_keys import create_key, revoke_key
from graph_memory_mcp.graph_memory.authorship import PROTECTED_FIELDS, strip_protected
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import (
    create_node,
    get_node,
    update_node,
)
from graph_memory_mcp.graph_memory.mcp_handlers_relations import create_relation
from graph_memory_mcp.graph_memory.owner_scope import (
    OwnerTokenMiddleware,
    ProjectDenied,
    bind_api_key,
    configure_owner_scope,
)
from graph_memory_mcp.graph_memory.utils import normalize_owner_id


@pytest.fixture(autouse=True)
def _reset_scope():
    configure_owner_scope("client")
    yield
    configure_owner_scope("client")


def test_protected_fields_are_central():
    assert PROTECTED_FIELDS == {
        "created_by",
        "created_at",
        "updated_by",
        "updated_at",
    }
    assert strip_protected(
        {"text": "x", "created_by": "bob", "created_at": 1, "extra": 2}
    ) == {"text": "x", "extra": 2}


def test_instructions_differ_by_mode():
    client = _mcp_instructions("client")
    header = _mcp_instructions("header")
    token = _mcp_instructions("token")
    assert "source_updated_at" in client
    assert "server-managed updated_at" in client
    assert "metadata.created_by" in client
    assert "metadata.updated_by" in client
    assert "author" not in client.lower()
    assert "pass owner_id" in client.lower()
    assert "metadata.created_by" in header
    assert "author" not in header.lower()
    assert "API key" in token
    assert "first project" in token
    assert "author" not in token.lower()


def test_foreign_project_gives_403(tmp_path):
    configure_owner_scope("token")
    record, _raw = create_key(tmp_path / "keys.json", "alice", ["p1"])
    with bind_api_key(record):
        with pytest.raises(ProjectDenied) as denied:
            normalize_owner_id("other")
        assert denied.value.status == 403


def test_revoked_key_gives_401(tmp_path):
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

    import asyncio

    sent = asyncio.run(_call())
    assert "yes" not in called
    assert sent[0]["status"] == 401


@pytest.mark.integration
def test_client_mode_without_metadata_attribution_leaves_fields_empty(memory_backend):
    owner = f"pytest_auth_{uuid.uuid4().hex[:8]}"
    result = create_node(
        memory_backend.db,
        memory_backend.config,
        text=f"no attribution {uuid.uuid4().hex[:8]}",
        owner_id=owner,
        auto_link=False,
    )
    assert result["success"]
    node = result["node"]
    assert node.get("created_at") is not None
    assert node.get("updated_at") is not None
    assert node.get("created_by") in (None, "")
    assert node.get("updated_by") in (None, "")


@pytest.mark.integration
def test_client_mode_reads_created_by_and_updated_by_from_metadata(memory_backend):
    owner = f"pytest_auth_{uuid.uuid4().hex[:8]}"
    result = create_node(
        memory_backend.db,
        memory_backend.config,
        text=f"with metadata {uuid.uuid4().hex[:8]}",
        owner_id=owner,
        metadata={"created_by": "alice", "updated_by": "bob"},
        auto_link=False,
    )
    assert result["success"], result
    node = result["node"]
    assert node["created_by"] == "alice"
    assert node["updated_by"] == "bob"
    assert node["metadata"]["created_by"] == "alice"
    assert node["metadata"]["updated_by"] == "bob"
    assert node.get("created_at") is not None
    assert node.get("updated_at") is not None


@pytest.mark.integration
def test_client_mode_update_copies_metadata_created_by(memory_backend):
    owner = f"pytest_auth_{uuid.uuid4().hex[:8]}"
    created = create_node(
        memory_backend.db,
        memory_backend.config,
        text=f"meta keep {uuid.uuid4().hex[:8]}",
        owner_id=owner,
        metadata={"created_by": "alice", "note": "keep"},
        auto_link=False,
    )
    assert created["success"], created
    node = created["node"]
    assert node["created_by"] == "alice"
    assert node.get("updated_by") in (None, "")
    assert node["metadata"]["created_by"] == "alice"
    updated = update_node(
        memory_backend.db,
        node_id=node["node_id"],
        owner_id=owner,
        metadata={"created_by": "mallory", "updated_by": "carol"},
    )
    assert updated["success"], updated
    after = updated["node"]
    assert after["created_by"] == "mallory"
    assert after["updated_by"] == "carol"
    assert after["metadata"]["created_by"] == "mallory"
    assert after["metadata"]["updated_by"] == "carol"
    assert after["metadata"]["note"] == "keep"
    assert after["created_at"] == node["created_at"]
    assert after.get("updated_at") is not None


@pytest.mark.integration
def test_token_mode_stores_key_name_not_client_author(memory_backend, tmp_path):
    configure_owner_scope("token")
    owner = f"pytest_tok_{uuid.uuid4().hex[:8]}"
    record, _raw = create_key(tmp_path / "keys.json", "alice", [owner])
    with bind_api_key(record):
        result = create_node(
            memory_backend.db,
            memory_backend.config,
            text=f"forged attribution {uuid.uuid4().hex[:8]}",
            owner_id=owner,
            metadata={
                "created_by": "bob",
                "updated_by": "mallory",
                "created_at": 1,
                "note": "keep",
            },
            auto_link=False,
        )
    assert result["success"], result
    node = result["node"]
    assert node["created_by"] == "alice"
    assert node.get("updated_by") == "alice"
    assert node.get("metadata", {}).get("created_by") in (None, "")
    assert node.get("metadata", {}).get("updated_by") in (None, "")
    assert "created_at" not in (node.get("metadata") or {})
    assert node["metadata"]["note"] == "keep"


@pytest.mark.integration
def test_created_by_stays_on_update_updated_fields_change(memory_backend, tmp_path):
    configure_owner_scope("token")
    owner = f"pytest_tok_{uuid.uuid4().hex[:8]}"
    record, _raw = create_key(tmp_path / "keys.json", "alice", [owner])
    with bind_api_key(record):
        created = create_node(
            memory_backend.db,
            memory_backend.config,
            text=f"before update {uuid.uuid4().hex[:8]}",
            owner_id=owner,
            metadata={"created_by": "bob"},
            auto_link=False,
        )
        assert created["success"]
        node = created["node"]
        created_by = node["created_by"]
        created_at = node["created_at"]
        time.sleep(0.02)
        updated = update_node(
            memory_backend.db,
            node_id=node["node_id"],
            owner_id=owner,
            text=f"after update {uuid.uuid4().hex[:8]}",
            metadata={"created_by": "mallory", "updated_by": "eve"},
        )
    assert updated["success"]
    after = updated["node"]
    assert created_by == "alice"
    assert after["created_by"] == "alice"
    assert after["created_at"] == created_at
    assert after.get("updated_by") == "alice"
    assert after.get("updated_at") is not None
    assert after["updated_at"] >= created_at
    assert after.get("metadata", {}).get("created_by") in (None, "")
    assert after.get("metadata", {}).get("updated_by") in (None, "")


@pytest.mark.integration
def test_relation_attribution_follows_properties_or_the_key(memory_backend, tmp_path):
    db = memory_backend.db
    cfg = memory_backend.config
    owner = f"pytest_rel_{uuid.uuid4().hex[:8]}"
    left = create_node(db, cfg, text="left", owner_id=owner, auto_link=False)
    right = create_node(db, cfg, text="right", owner_id=owner, auto_link=False)
    assert left["success"] and right["success"]
    linked = create_relation(
        db,
        from_id=left["node"]["node_id"],
        to_id=right["node"]["node_id"],
        relation_type="RELATED_TO",
        properties={"created_by": "alice", "updated_by": "bob", "note": "keep"},
        owner_id=owner,
        config=cfg,
    )
    assert linked["success"], linked
    assert linked["created_by"] == "alice"
    assert linked["updated_by"] == "bob"

    configure_owner_scope("token")
    record, _raw = create_key(tmp_path / "keys.json", "alice", [owner])
    with bind_api_key(record):
        forged = create_relation(
            db,
            from_id=right["node"]["node_id"],
            to_id=left["node"]["node_id"],
            relation_type="MENTIONS",
            properties={"created_by": "mallory", "updated_by": "eve"},
            owner_id=owner,
            config=cfg,
        )
    assert forged["success"], forged
    assert forged["created_by"] == "alice"
    assert forged["updated_by"] == "alice"


@pytest.mark.integration
def test_export_import_keeps_created_by_and_created_at(memory_backend):
    db = memory_backend.db
    src = f"pytest_audimp_{uuid.uuid4().hex[:8]}"
    dst = f"{src}_copy"
    created = create_node(
        db,
        memory_backend.config,
        text=f"audit roundtrip {uuid.uuid4().hex[:8]}",
        owner_id=src,
        metadata={"created_by": "alice"},
        auto_link=False,
    )
    assert created["success"], created
    node = created["node"]
    exported = admin.export_owner(db, owner_id=src, include_embeddings=True)
    imported = admin.import_owner(
        db,
        owner_id=dst,
        nodes=exported["nodes"],
        relations=exported["relations"],
        preserve_audit=True,
    )
    assert imported["success"], imported
    got = get_node(db, node_id=node["node_id"], owner_id=dst)
    assert got["success"], got
    assert got["node"]["created_by"] == node["created_by"] == "alice"
    assert got["node"]["created_at"] == node["created_at"]
