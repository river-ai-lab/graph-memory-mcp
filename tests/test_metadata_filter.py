"""metadata_filter keys are rejected the same way on both backends."""

import pytest

from graph_memory_mcp.graph_memory.backends.arcade_search import _attribute_where
from graph_memory_mcp.graph_memory.backends.falkor_search import (
    ann_rows,
    build_metadata_filter_clauses,
)


def test_unknown_metadata_filter_key_uses_one_message() -> None:
    with pytest.raises(ValueError, match="allowed: \\['confidence_min'") as falkor:
        build_metadata_filter_clauses({"nope": "x"})
    with pytest.raises(ValueError, match="allowed: \\['confidence_min'") as arcade:
        _attribute_where(
            "Fact",
            include_outdated=False,
            status=None,
            metadata_filter={"nope": "x"},
            exclude_node_id=None,
            now_ms=1,
        )
    assert str(falkor.value) == str(arcade.value)


class _Store:
    def __init__(self) -> None:
        self.query = ""
        self.params: dict = {}

    def rows(self, query: str, params: dict) -> list:
        self.query = query
        self.params = params
        return []


def test_ann_rows_reuses_property_filters() -> None:
    store = _Store()
    ann_rows(
        store,
        node_type="Fact",
        embedding=[0.1],
        owner_id="team",
        ann_k=8,
        limit=3,
        max_distance=0.4,
        include_ttl=True,
        metadata_filter={"project": "api"},
        exclude_node_id="abc",
    )
    assert "(node.status IS NULL OR node.status = 'active')" in store.query
    assert "(node.expires_at IS NULL OR node.expires_at > timestamp())" in store.query
    assert "node.project = $mf_project" in store.query
    assert "node.uid <> $exclude_uid" in store.query
    assert store.params["mf_project"] == "api"
    assert store.params["exclude_uid"] == "abc"
