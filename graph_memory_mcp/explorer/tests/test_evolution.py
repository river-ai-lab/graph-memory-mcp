"""Evolution integration: owner scope, hydration and honest partial-map diffs."""

from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from graph_memory_mcp.explorer import evolution
from graph_memory_mcp.explorer.app import create_app

NOW = datetime.now(timezone.utc)
MS = int(NOW.timestamp() * 1000)


class Client:
    connected = True
    url = "mock://memory"

    def __init__(self):
        self.calls = []

    async def connect(self):
        self.connected = True

    async def close(self):
        self.connected = False

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        assert name == "get_node"
        assert arguments["owner_id"] == "luminaria"
        return {
            "success": True,
            "node": {
                "node_id": arguments["node_id"],
                "node_type": "Fact",
                "text": "Verified rule",
                "created_at": MS - 3600000,
                "status": "active",
            },
        }


def test_unconfigured_evolution_has_actionable_error(monkeypatch):
    monkeypatch.setattr(evolution, "graphdiff_available", lambda: False)
    with TestClient(create_app(Client())) as client:
        response = client.post("/api/evolution/capture", json={})
        assert response.status_code == 503
        assert "--graph-diff-path" in response.json()["error"]


def test_capture_hydrates_only_the_requested_owner_and_period_is_partial():
    pytest.importorskip("graphdiff.memory")
    upstream = Client()
    with TestClient(create_app(upstream)) as client:
        response = client.post(
            "/api/evolution/capture",
            json={
                "owner_id": "luminaria",
                "node_ids": ["a", "b"],
                "edges": [
                    {
                        "from_id": "a",
                        "to_id": "b",
                        "relation_type": "FOLLOWS_FROM",
                        "properties": {"created_at": MS - 1000},
                    }
                ],
            },
        )
        assert response.status_code == 200
        capture = response.json()["capture"]
        assert capture["coverage"] == "partial"
        result = client.post(
            "/api/evolution/activity",
            json={
                "owner_id": "luminaria",
                "capture": capture,
                "start": (NOW - timedelta(days=7)).isoformat(),
                "end": NOW.isoformat(),
            },
        ).json()
        assert len(result["created_nodes"]) == 2
        assert len(result["created_edges"]) == 1
        assert result["limitations"]
        assert [c[0] for c in upstream.calls] == ["get_node", "get_node"]
        forbidden = client.post(
            "/api/tool", json={"tool": "create_node", "arguments": {}}
        )
        assert forbidden.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"owner_id": "bad/owner", "node_ids": ["a"]},
        {"owner_id": "luminaria", "node_ids": []},
        {"owner_id": "luminaria", "node_ids": ["a", "a"]},
    ],
)
def test_invalid_capture_never_reads_upstream(body):
    pytest.importorskip("graphdiff.memory")
    upstream = Client()
    with TestClient(create_app(upstream)) as client:
        assert client.post("/api/evolution/capture", json=body).status_code == 400
        assert not upstream.calls


def test_compare_rejects_cross_owner_snapshots_and_reports_real_status_change():
    pytest.importorskip("graphdiff.memory")
    before = {
        "owner_id": "luminaria",
        "scope": "loaded-map",
        "coverage": "partial",
        "timestamp": NOW.isoformat(),
        "nodes": [
            {
                "id": "a",
                "label": "Fact",
                "properties": {"text": "Rule", "status": "active"},
            }
        ],
        "edges": [],
    }
    after = {
        **before,
        "timestamp": (NOW + timedelta(seconds=1)).isoformat(),
        "nodes": [
            {
                "id": "a",
                "label": "Fact",
                "properties": {"text": "Rule", "status": "outdated"},
            }
        ],
    }
    with TestClient(create_app(Client())) as client:
        response = client.post(
            "/api/evolution/compare",
            json={"owner_id": "luminaria", "before": before, "after": after},
        )
        assert response.json()["summary"]["nodes"]["modified"] == 1
        assert response.json()["semantics"] == "observed-view-diff"
        assert (
            client.post(
                "/api/evolution/compare",
                json={"owner_id": "riverlab", "before": before, "after": after},
            ).status_code
            == 400
        )
