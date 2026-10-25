"""Seed with the pre-page get_context code and dump default responses.

Run with the repo venv. The script drops the editable-install finder and
imports ``graph_memory_mcp`` from the worktree path passed as argv[1]
(commit fe5578d). argv[2] is the JSON output path.

Embeddings are not loaded. ``create_node`` still runs the old write path;
a missing vector is stored as NULL, which ``get_context`` does not read.
"""

from __future__ import annotations

import inspect
import json
import sys
import time
from pathlib import Path


def _use_old_tree(root: str) -> None:
    sys.path.insert(0, root)
    sys.meta_path = [
        hook
        for hook in sys.meta_path
        if "editable" not in type(hook).__name__.lower()
        and "editable" not in getattr(type(hook), "__module__", "").lower()
    ]
    sys.path_hooks = [
        hook for hook in sys.path_hooks if "editable" not in repr(hook).lower()
    ]


def _plain(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "items"):
        return {str(key): _plain(item) for key, item in value.items()}
    return str(value)


class _DummyEmbedding:
    dimension = 0

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    def ping(self) -> bool:
        return False

    def get_embedding(self, *args, **kwargs):
        del args, kwargs
        return []

    def get_embeddings_batch(self, texts, *args, **kwargs):
        del args, kwargs
        return [[] for _ in texts]


def main() -> None:
    old_root = sys.argv[1]
    out_path = Path(sys.argv[2])
    _use_old_tree(old_root)

    import graph_memory_mcp.graph_memory.embedding_service as embedding_service

    embedding_service.EmbeddingService = _DummyEmbedding

    import graph_memory_mcp
    import graph_memory_mcp.graph_memory.mcp_handlers_nodes as nodes
    from graph_memory_mcp.config import load_mcp_server_config
    from graph_memory_mcp.graph_memory.database import open_store
    from graph_memory_mcp.graph_memory.mcp_handlers_graph import get_context
    from graph_memory_mcp.graph_memory.mcp_handlers_nodes import create_node
    from graph_memory_mcp.graph_memory.mcp_handlers_relations import create_relation

    if "gm-old" not in str(Path(graph_memory_mcp.__file__).resolve()):
        raise SystemExit(f"refusing to seed with {graph_memory_mcp.__file__}")

    uids = iter(
        [
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "fffffffffffffffffffffff00000001",
            "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            "00000000000000000000000000000001",
            "00000000000000000000000000000002",
            "11111111111111111111111111111111",
            "dddddddddddddddddddddddddddddddd",
            "small000000000000000000000000001",
            "small000000000000000000000000002",
            "small000000000000000000000000003",
            "auth0000000000000000000000000001",
            "auth0000000000000000000000000002",
        ]
    )
    nodes.new_uid = lambda: next(uids)

    cfg = load_mcp_server_config().model_copy(
        update={"graph_backend": "falkordb", "auto_create_indexes": False}
    )
    db = open_store(cfg)
    if not db.connect():
        raise SystemExit("FalkorDB connect failed")
    db.set_embedding_service(_DummyEmbedding())

    hub_owner = "compat_hub"
    small_owner = "compat_small"
    auth_owner = "compat_auth"
    for owner in (hub_owner, small_owner, auth_owner):
        db.delete_owner_graph(owner)

    def add(owner, text, **kwargs):
        created = create_node(
            db,
            cfg,
            text=text,
            owner_id=owner,
            auto_link=False,
            check_duplicates=False,
            **kwargs,
        )
        if not created.get("success"):
            raise SystemExit(f"create_node failed: {created}")
        return created["node"]["node_id"]

    def link(owner, from_id, to_id, relation_type):
        linked = create_relation(
            db,
            from_id=from_id,
            to_id=to_id,
            relation_type=relation_type,
            owner_id=owner,
            config=cfg,
        )
        if not linked.get("success"):
            raise SystemExit(f"create_relation failed: {linked}")

    hub = add(
        hub_owner,
        "Hub fact for the gateway",
        metadata={"topic": "gateway", "valid_from": "2026-01-01"},
    )
    contra = add(hub_owner, "Hub contradicts this neighbor")
    follows = add(hub_owner, "This follows from the hub")
    rel1 = add(hub_owner, "Related neighbor one")
    rel2 = add(hub_owner, "Related neighbor two")
    entity = add(
        hub_owner, "Routing service", node_type="Entity", entity_type="Service"
    )
    outdated = add(
        hub_owner,
        "Outdated neighbor kept in the store",
        status="outdated",
    )
    link(hub_owner, hub, contra, "CONTRADICTS")
    link(hub_owner, follows, hub, "FOLLOWS_FROM")
    link(hub_owner, hub, rel1, "RELATED_TO")
    link(hub_owner, hub, rel2, "RELATED_TO")
    link(hub_owner, hub, entity, "MENTIONS")
    link(hub_owner, hub, outdated, "RELATED_TO")

    small = add(small_owner, "A short fact")
    small_neighbor = add(small_owner, "One neighbor")
    small_outdated = add(small_owner, "Old small fact", status="outdated")
    link(small_owner, small, small_neighbor, "RELATED_TO")
    link(small_owner, small, small_outdated, "RELATED_TO")

    auth_node = add(auth_owner, "Auth project fact")
    auth_neighbor = add(auth_owner, "Auth project neighbor")
    link(auth_owner, auth_node, auth_neighbor, "RELATED_TO")

    def indexes(owner: str):
        try:
            return _plain(db.rows("CALL db.indexes()", owner_id=owner))
        except Exception as exc:  # noqa: BLE001
            return [{"error": str(exc)}]

    def call(name, kind, **kwargs):
        started = time.perf_counter()
        response = get_context(db, cfg, **kwargs)
        elapsed = (time.perf_counter() - started) * 1000
        body = _plain(response)
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        return {
            "name": name,
            "kind": kind,
            "kwargs": _plain(kwargs),
            "response": body,
            "elapsed_ms": round(elapsed, 3),
            "bytes": len(encoded),
        }

    cases = [
        call("hub_default", "handler", node_id=hub, owner_id=hub_owner),
        call(
            "hub_explicit",
            "handler",
            node_id=hub,
            owner_id=hub_owner,
            depth=1,
            max_nodes=20,
            offset=0,
        ),
        call(
            "hub_include_outdated",
            "handler",
            node_id=hub,
            owner_id=hub_owner,
            include_outdated=True,
        ),
        call("small_default", "handler", node_id=small, owner_id=small_owner),
        call("small_leaf", "handler", node_id=small_neighbor, owner_id=small_owner),
        call(
            "missing",
            "handler",
            node_id="missing00000000000000000000000001",
            owner_id=small_owner,
        ),
    ]

    def timed_page(name, **kwargs):
        samples = []
        response = None
        for _ in range(5):
            started = time.perf_counter()
            response = get_context(db, cfg, **kwargs)
            samples.append((time.perf_counter() - started) * 1000)
        body = _plain(response)
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        samples.sort()
        return {
            "name": name,
            "kind": "handler_page",
            "kwargs": _plain(kwargs),
            "response": body,
            "elapsed_ms_median": round(samples[len(samples) // 2], 3),
            "bytes": len(encoded),
            "nodes": len(body.get("nodes") or []),
            "edges": len(body.get("edges") or []),
        }

    paged = [
        timed_page(
            "hub_offset",
            node_id=hub,
            owner_id=hub_owner,
            depth=1,
            max_nodes=2,
            offset=2,
        )
    ]

    dense_id = None
    try:
        found = db.rows(
            "MATCH (n) WHERE n.text CONTAINS 'Gateway hub' RETURN n.uid LIMIT 1",
            owner_id="dense_map",
        )
        if found:
            dense_id = str(found[0][0])
    except Exception:  # noqa: BLE001
        dense_id = None
    if dense_id:
        paged.append(
            timed_page(
                "dense_offset",
                node_id=dense_id,
                owner_id="dense_map",
                depth=1,
                max_nodes=10,
                offset=10,
            )
        )
        paged.append(
            timed_page(
                "dense_offset0",
                node_id=dense_id,
                owner_id="dense_map",
                depth=1,
                max_nodes=10,
                offset=0,
            )
        )

    from graph_memory_mcp.graph_memory.api_keys import create_key
    from graph_memory_mcp.graph_memory.owner_scope import bind_api_key
    from graph_memory_mcp.server_auth import GraphMemoryAuthMCP

    keys = Path("/tmp/compat-old-keys.json")
    keys.unlink(missing_ok=True)
    record, _raw = create_key(keys, "compat", [auth_owner])
    auth_cfg = cfg.model_copy(
        update={
            "owner_scope": "token",
            "admin_token": "compat-admin",
            "api_keys_file": str(keys),
            "auto_create_indexes": False,
        }
    )
    server = GraphMemoryAuthMCP(auth_cfg)
    signature = inspect.signature(server.get_context)
    with bind_api_key(record):
        auth_response = server.get_context(node_id=auth_node)
    auth_body = _plain(auth_response)
    direct = _plain(get_context(db, cfg, node_id=auth_node, owner_id=auth_owner))
    if auth_body != direct:
        raise SystemExit("old --auth get_context differed from the handler")
    cases.append(
        {
            "name": "auth_default",
            "kind": "auth_tool",
            "kwargs": {"node_id": auth_node},
            "owner_id": auth_owner,
            "response": auth_body,
            "elapsed_ms": None,
            "bytes": len(
                json.dumps(auth_body, sort_keys=True, separators=(",", ":")).encode()
            ),
            "schema": {
                "parameters": list(signature.parameters),
                "required": [
                    name
                    for name, param in signature.parameters.items()
                    if param.default is inspect.Parameter.empty
                ],
            },
        }
    )

    payload = {
        "package": str(Path(graph_memory_mcp.__file__).resolve()),
        "backend": type(db).__name__,
        "ids": {
            "hub": hub,
            "contra": contra,
            "follows": follows,
            "rel1": rel1,
            "rel2": rel2,
            "entity": entity,
            "outdated": outdated,
            "small": small,
            "small_neighbor": small_neighbor,
            "small_outdated": small_outdated,
            "auth": auth_node,
            "auth_neighbor": auth_neighbor,
            "missing": "missing00000000000000000000000001",
            "dense": dense_id,
        },
        "indexes_after_seed": {
            owner: indexes(owner) for owner in (hub_owner, small_owner, auth_owner)
        },
        "cases": cases,
        "paged": paged,
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
