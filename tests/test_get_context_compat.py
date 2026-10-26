"""Default get_context stays identical on data written by fe5578d.

The old commit seeds FalkorDB. This process, on the current code, reads the
same graphs. Calls that omit ``page`` and use offset 0 must match, including
node order, edge order, and fields. ``page`` / offset > 0 may add edges.
"""

from __future__ import annotations

import inspect
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest

import graph_memory_mcp.base_server as base_server
from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory.api_keys import create_key
from graph_memory_mcp.graph_memory.database import open_store
from graph_memory_mcp.graph_memory.mcp_handlers_graph import get_context
from graph_memory_mcp.graph_memory.owner_scope import (
    bind_api_key,
    configure_owner_scope,
    owner_scope,
)
from graph_memory_mcp.server import GraphMemoryMCP
from graph_memory_mcp.server_auth import GraphMemoryAuthMCP

OLD_COMMIT = "fe5578de22145f9379fa5c3ddc3538e0dcc9459a"
REPO = Path(__file__).resolve().parents[1]
DUMP = REPO / "tests" / "compat" / "old_get_context_dump.py"
GOLDEN = REPO / "tests" / "fixtures" / "get_context_default_golden.json"
WORKTREE = Path("/tmp/gm-old-fe5578d")
_TIME_KEYS = {"created_at", "updated_at"}


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


def _canonical(response: dict) -> dict:
    nodes = []
    for node in response["nodes"]:
        nodes.append(
            {key: value for key, value in node.items() if key not in _TIME_KEYS}
        )
    edges = []
    for edge in response["edges"]:
        props = edge.get("properties") or {}
        if not isinstance(props, dict):
            props = {"_raw": str(props)}
        props = {key: value for key, value in props.items() if key not in _TIME_KEYS}
        edges.append(
            {
                "from_id": edge["from_id"],
                "to_id": edge["to_id"],
                "relation_type": edge["relation_type"],
                "properties": props,
            }
        )
    edges.sort(
        key=lambda item: (
            item["from_id"],
            item["relation_type"],
            item["to_id"],
            json.dumps(item["properties"], sort_keys=True),
        )
    )
    return {
        "success": response["success"],
        "depth": response["depth"],
        "max_nodes": response["max_nodes"],
        "has_offset": "offset" in response,
        "has_more": "has_more" in response,
        "nodes": nodes,
        "edges": edges,
    }


def _ensure_old_root() -> Path:
    head = WORKTREE / "graph_memory_mcp" / "server.py"
    if head.is_file():
        return WORKTREE
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{OLD_COMMIT}^{{commit}}"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip(f"{OLD_COMMIT} is not in this clone")
    subprocess.check_call(
        ["git", "worktree", "add", "--detach", str(WORKTREE), OLD_COMMIT],
        cwd=REPO,
    )
    return WORKTREE


def _seed_with_old_code(tmp_path: Path) -> dict:
    old_root = _ensure_old_root()
    out = tmp_path / "old_get_context.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(old_root)
    env["GRAPH_BACKEND"] = "falkordb"
    env["AUTO_CREATE_INDEXES"] = "false"
    env.setdefault("FALKORDB_PASSWORD", "falkordb123")
    subprocess.check_call(
        [sys.executable, str(DUMP), str(old_root), str(out)],
        cwd=REPO,
        env=env,
    )
    return json.loads(out.read_text())


def _new_store():
    cfg = load_mcp_server_config().model_copy(
        update={"graph_backend": "falkordb", "auto_create_indexes": False}
    )
    db = open_store(cfg)
    if not db.connect():
        pytest.fail("FalkorDB connect failed")
    return cfg, db


def _indexes(db, owner: str):
    try:
        return _plain(db.rows("CALL db.indexes()", owner_id=owner))
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


def _edge_keys(response: dict) -> list[tuple[str, str, str]]:
    return [
        (edge["from_id"], edge["relation_type"], edge["to_id"])
        for edge in response["edges"]
    ]


def _median_call(db, cfg, kwargs: dict) -> tuple[dict, float, int]:
    samples = []
    response = None
    for _ in range(5):
        started = time.perf_counter()
        response = get_context(db, cfg, **kwargs)
        samples.append((time.perf_counter() - started) * 1000)
    body = _plain(response)
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return body, statistics.median(samples), len(encoded)


@pytest.mark.integration
def test_get_context_default_matches_old_code_on_same_falkordb(tmp_path):
    """Seed with fe5578d, then require identical default get_context responses."""
    old = _seed_with_old_code(tmp_path)
    assert "gm-old" in old["package"]
    assert old["backend"] == "FalkorDBClient"
    cfg, db = _new_store()

    golden_cases = {}
    for case in old["cases"]:
        kwargs = dict(case["kwargs"])
        if case["kind"] == "auth_tool":
            assert "page" not in case["schema"]["parameters"]
            assert "owner_id" not in case["schema"]["parameters"]
            assert "node_id" in case["schema"]["required"]

            previous_embed = base_server.EmbeddingService
            previous_scope = owner_scope()

            class _Dummy:
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

            base_server.EmbeddingService = _Dummy
            keys = tmp_path / "keys.json"
            record, _raw = create_key(keys, "compat", [case["owner_id"]])
            auth_cfg = cfg.model_copy(
                update={
                    "owner_scope": "token",
                    "admin_token": "compat-admin",
                    "api_keys_file": str(keys),
                    "auto_create_indexes": False,
                }
            )
            try:
                auth = GraphMemoryAuthMCP(auth_cfg)
                auth_sig = inspect.signature(auth.get_context)
                assert "owner_id" not in auth_sig.parameters
                assert "page" in auth_sig.parameters
                assert auth_sig.parameters["page"].default is False
                assert "page" not in [
                    name
                    for name, param in auth_sig.parameters.items()
                    if param.default is inspect.Parameter.empty
                ]
                plain_server = GraphMemoryMCP(
                    cfg.model_copy(update={"auto_create_indexes": False})
                )
                public = inspect.signature(plain_server.get_context)
                assert "page" in public.parameters
                assert public.parameters["page"].default is False
                assert "owner_id" in public.parameters
                assert "page" not in [
                    name
                    for name, param in public.parameters.items()
                    if param.default is inspect.Parameter.empty
                ]
                with bind_api_key(record):
                    fresh = _plain(auth.get_context(**kwargs))
            finally:
                base_server.EmbeddingService = previous_embed
                configure_owner_scope(previous_scope)
        else:
            assert "page" not in kwargs
            fresh = _plain(get_context(db, cfg, **kwargs))
        assert fresh == case["response"], case["name"]
        assert "offset" not in fresh
        assert "has_more" not in fresh
        golden_cases[case["name"]] = _canonical(fresh)

    for owner, before in old["indexes_after_seed"].items():
        assert _indexes(db, owner) == before

    golden = {
        "old_commit": OLD_COMMIT,
        "note": (
            "Default get_context (page omitted, offset 0) on a FalkorDB graph "
            "seeded by that commit. created_at/updated_at are omitted. "
            "Edges are sorted so the fixture is stable across reseeds; the test "
            "still requires the live old and new edge lists to be identical."
        ),
        "cases": golden_cases,
    }
    if os.environ.get("WRITE_GOLDEN") == "1" or not GOLDEN.is_file():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n")
    stored = json.loads(GOLDEN.read_text())
    assert stored["old_commit"] == OLD_COMMIT
    assert stored["cases"] == golden_cases

    page_report = []
    for item in old["paged"]:
        kwargs = dict(item["kwargs"])
        fresh, median_ms, size = _median_call(db, cfg, kwargs)
        assert [node["node_id"] for node in fresh["nodes"]] == [
            node["node_id"] for node in item["response"]["nodes"]
        ]
        assert _plain(fresh["nodes"]) == _plain(item["response"]["nodes"])
        old_edges = _edge_keys(item["response"])
        new_edges = _edge_keys(fresh)
        extra = [edge for edge in new_edges if edge not in set(old_edges)]
        assert set(old_edges) <= set(new_edges)
        if item["name"] == "hub_offset":
            assert extra, "offset>0 should attach edges that leave the page"
            assert size > item["bytes"]
        if item["name"] == "dense_offset":
            assert extra, "dense_map offset>0 should attach edges back to the hub"
            assert size > item["bytes"]
        page_report.append(
            {
                "name": item["name"],
                "kwargs": kwargs,
                "old_nodes": item["nodes"],
                "new_nodes": len(fresh["nodes"]),
                "old_edges": item["edges"],
                "new_edges": len(fresh["edges"]),
                "extra_edges": [list(edge) for edge in extra],
                "old_bytes": item["bytes"],
                "new_bytes": size,
                "old_ms_median": item["elapsed_ms_median"],
                "new_ms_median": round(median_ms, 3),
            }
        )
        # page=true at this offset is the same node window plus the same closure.
        if "page" not in kwargs and kwargs.get("offset", 0) > 0:
            paged_kwargs = dict(kwargs, page=True)
            paged, _paged_ms, paged_size = _median_call(db, cfg, paged_kwargs)
            assert [node["node_id"] for node in paged["nodes"]] == [
                node["node_id"] for node in fresh["nodes"]
            ]
            assert _edge_keys(paged) == new_edges
            page_report[-1]["page_true_bytes"] = paged_size

    dense_first = next(
        (item for item in old["paged"] if item["name"] == "dense_offset0"), None
    )
    if dense_first is not None:
        kwargs = dict(dense_first["kwargs"], page=True)
        fresh, median_ms, size = _median_call(db, cfg, kwargs)
        old_ids = [node["node_id"] for node in dense_first["response"]["nodes"]]
        new_ids = [node["node_id"] for node in fresh["nodes"]]
        page_report.append(
            {
                "name": "dense_page_true_offset0",
                "note": (
                    "page=true at offset 0 is the stable id order, not the "
                    "priority walk, and a full page adds edges outside that page."
                ),
                "old_nodes": dense_first["nodes"],
                "new_nodes": len(fresh["nodes"]),
                "same_node_set": set(old_ids) == set(new_ids),
                "same_node_order": old_ids == new_ids,
                "old_edges": dense_first["edges"],
                "new_edges": len(fresh["edges"]),
                "extra_edges": len(
                    set(_edge_keys(fresh)) - set(_edge_keys(dense_first["response"]))
                ),
                "old_bytes": dense_first["bytes"],
                "new_bytes": size,
                "old_ms_median": dense_first["elapsed_ms_median"],
                "new_ms_median": round(median_ms, 3),
            }
        )

    assert page_report
