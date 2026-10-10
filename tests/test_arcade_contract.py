"""Arcade contract pieces that do not need a running ArcadeDB."""

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.backends.arcade_ops import _edge_rank, _visible
from graph_memory_mcp.graph_memory.backends.arcade_search import _attribute_where
from graph_memory_mcp.graph_memory.mcp_handlers_search import search
from graph_memory_mcp.graph_memory.relation_policy import neighbor_rank_expr


def test_default_fact_filter_hides_any_ttl():
    where, _params = _attribute_where(
        "Fact",
        include_outdated=False,
        status=None,
        metadata_filter=None,
        exclude_node_id=None,
        now_ms=1,
        include_ttl=False,
    )
    assert "expires_at IS NULL" in where
    assert "expires_at >" not in where


def test_include_ttl_keeps_unexpired_facts():
    where, _params = _attribute_where(
        "Fact",
        include_outdated=False,
        status=None,
        metadata_filter=None,
        exclude_node_id=None,
        now_ms=50,
        include_ttl=True,
    )
    assert "expires_at IS NULL OR expires_at > 50" in where


def test_edge_rank_prefers_contradicts_over_mentions():
    expr = neighbor_rank_expr(None, frozenset({"RELATED_TO", "MENTIONS"}))
    assert _edge_rank(expr, "CONTRADICTS") < _edge_rank(expr, "MENTIONS")


def test_visible_hides_living_ttl_unless_asked():
    living = {"status": "active", "expires_at": 10_000}
    assert _visible(living, False, 1, include_ttl=False) is False
    assert _visible(living, False, 1, include_ttl=True) is True
    assert _visible({"status": "active"}, False, 1) is True


class _EmptyEmbed:
    def get_embedding(self, text: str, kind: str = "passage"):
        del text, kind
        return []

    def ensure_search_indexes_if_missing(self, owner_id: str) -> None:
        del owner_id


class _Cache:
    def get_search(self, key):
        del key
        return None


def test_search_without_a_vector_is_an_error_not_an_empty_memory():
    db = _EmptyEmbed()
    db.cache = _Cache()
    result = search(db, MCPServerConfig(), query="anything", owner_id="default")
    assert result["success"] is False
    assert result["code"] == "memory_embedding_error"
    assert "results" not in result
