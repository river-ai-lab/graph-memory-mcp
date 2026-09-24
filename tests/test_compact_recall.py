"""Unit tests for compact recall envelopes (no FalkorDB)."""

from graph_memory_mcp.graph_memory.compact_recall import (
    decorate_recall_response,
    decorate_search_response,
    estimate_tokens,
    snippet_text,
    suggested_next_for_search,
)


def test_estimate_tokens_and_snippet():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert snippet_text("short", 100) == "short"
    long = "word " * 50
    snip = snippet_text(long, 40)
    assert snip.endswith("…")
    assert len(snip) <= 42


def test_decorate_search_full_adds_guidance():
    payload = {
        "success": True,
        "results": [
            {
                "node_id": "abc",
                "node_type": "Fact",
                "text": "Production Redis is at redis.internal",
                "similarity": 0.9,
            }
        ],
        "facts": [],
        "entities": [],
    }
    out = decorate_search_response(
        payload,
        compact=False,
        snippet_chars=180,
        token_budget=800,
        query="redis",
        owner_id="riverlab",
    )
    assert out["compact"] is False
    assert out["results"][0]["text"].startswith("Production Redis")
    assert out["suggested_next"]
    assert "get_context" in out["suggested_next"][0]
    assert "do_not" in out
    assert out["budget"]["mode"] == "full"
    # Must not mutate original
    assert "suggested_next" not in payload


def test_decorate_search_compact_uses_snippets_and_budget():
    long_text = "x" * 500
    payload = {
        "success": True,
        "results": [
            {
                "node_id": "n1",
                "node_type": "Fact",
                "text": long_text,
                "similarity": 0.95,
            },
            {
                "node_id": "n2",
                "node_type": "Fact",
                "text": long_text,
                "similarity": 0.9,
            },
            {
                "node_id": "n3",
                "node_type": "Fact",
                "text": long_text,
                "similarity": 0.85,
            },
        ],
        "facts": [],
        "entities": [],
    }
    out = decorate_search_response(
        payload,
        compact=True,
        snippet_chars=40,
        token_budget=30,
        query="x",
        owner_id="riverlab",
        metadata_filter={"project": "graph-diff"},
    )
    assert out["compact"] is True
    assert out["budget"]["truncated"] is True
    assert len(out["results"]) < 3 or "snippet" in out["results"][0]
    assert any("get_node" in s for s in out["suggested_next"])
    assert (
        "metadata_filter"
        in suggested_next_for_search(
            results=[],
            query="x",
            owner_id="riverlab",
            metadata_filter={"project": "graph-diff"},
        )[1]
    )


def test_decorate_recall_compact():
    payload = {
        "success": True,
        "seeds": [
            {
                "node_id": "s1",
                "node_type": "Fact",
                "text": "seed fact about auth",
                "similarity": 0.9,
            }
        ],
        "nodes": [
            {
                "node_id": "s1",
                "node_type": "Fact",
                "text": "seed fact about auth",
                "score": 0.9,
                "min_hop": 0,
            },
            {
                "node_id": "n2",
                "node_type": "Fact",
                "text": "neighbor " + ("y" * 400),
                "score": 0.5,
                "min_hop": 1,
            },
        ],
        "edges": [],
    }
    out = decorate_recall_response(
        payload,
        compact=True,
        snippet_chars=50,
        token_budget=40,
        owner_id="riverlab",
    )
    assert out["suggested_next"]
    assert out["budget"]["mode"] == "compact"
    assert "do_not" in out
