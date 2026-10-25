"""metadata_filter keys are rejected the same way on both backends."""

import pytest

from graph_memory_mcp.graph_memory.backends.arcade_search import _attribute_where
from graph_memory_mcp.graph_memory.backends.falkor_search import (
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
