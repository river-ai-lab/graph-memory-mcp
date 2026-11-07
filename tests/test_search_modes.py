"""search_mode: exact, fuzzy, bm25, hybrid on both stores; lexical index unit tests."""

from __future__ import annotations

import uuid

import pytest

from graph_memory_mcp.graph_memory.lexical_search import (
    LexicalIndex,
    normalize_hybrid_modes,
    normalize_search_mode,
    rrf_fuse,
)
from graph_memory_mcp.graph_memory.mcp_handlers_nodes import create_node
from graph_memory_mcp.graph_memory.mcp_handlers_search import search

ROWS = [
    [
        "a",
        "Fact",
        "Deploy job RUN_20250301T101500Z failed on node gpu-7",
        None,
        1,
        "{}",
        0.0,
    ],
    ["b", "Fact", "The billing service moved to PostgreSQL 16", None, 1, "{}", 0.0],
    [
        "c",
        "Fact",
        "Kubernetes cluster autoscaler limits set to 48Gi",
        None,
        1,
        "{}",
        0.0,
    ],
    ["d", "Fact", "Alice prefers dark roast coffee", None, 1, "{}", 0.0],
]


def _ids(hits):
    return [row[0] for row, _ in hits]


@pytest.mark.nodb
def test_bm25_ranks_keyword_match_first():
    idx = LexicalIndex.build(ROWS)
    assert _ids(idx.search("billing postgresql", "bm25", 10))[0] == "b"
    assert idx.search("nothing matches here", "bm25", 10) == []


@pytest.mark.nodb
def test_fuzzy_tolerates_typos_bm25_does_not():
    idx = LexicalIndex.build(ROWS)
    assert idx.search("kubernetis autoscaller", "bm25", 10) == []
    assert _ids(idx.search("kubernetis autoscaller", "fuzzy", 10))[0] == "c"


@pytest.mark.nodb
def test_exact_requires_phrase():
    idx = LexicalIndex.build(ROWS)
    assert _ids(idx.search("dark roast", "exact", 10)) == ["d"]
    assert idx.search("roast dark", "exact", 10) == []
    assert _ids(idx.search('"gpu-7" "deploy job"', "exact", 10)) == ["a"]


@pytest.mark.nodb
def test_mode_parsing_and_rrf():
    assert normalize_search_mode(None) == "embedding"
    assert normalize_search_mode("vector") == "embedding"
    assert normalize_search_mode("BM25") == "bm25"
    with pytest.raises(ValueError):
        normalize_search_mode("magic")
    assert normalize_hybrid_modes(None) == ("embedding", "bm25")
    with pytest.raises(ValueError):
        normalize_hybrid_modes(["hybrid"])
    fused = rrf_fuse([["x", "y"], ["y", "z"]])
    assert max(fused, key=fused.get) == "y"


def test_search_modes_on_store(memory_backend):
    cfg, db = memory_backend.config, memory_backend.db
    owner = f"pytest_modes_{uuid.uuid4().hex[:8]}"
    texts = [r[2] for r in ROWS]
    ids = {}
    for t in texts:
        r = create_node(db, cfg, text=t, owner_id=owner, auto_link=False)
        ids[t] = r["node"]["node_id"]
    try:
        legacy = search(db, cfg, query="coffee preferences", owner_id=owner)
        explicit = search(
            db, cfg, query="coffee preferences", owner_id=owner, search_mode="embedding"
        )
        assert [x["node_id"] for x in legacy["results"]] == [
            x["node_id"] for x in explicit["results"]
        ]
        assert legacy["results"][0]["node_id"] == ids[texts[3]]

        r = search(
            db, cfg, query="RUN_20250301T101500Z", owner_id=owner, search_mode="exact"
        )
        assert [x["node_id"] for x in r["results"]] == [ids[texts[0]]]
        assert r["results"][0]["match"] == "exact"

        r = search(
            db, cfg, query="postgres billing", owner_id=owner, search_mode="bm25"
        )
        assert r["results"][0]["node_id"] == ids[texts[1]]

        r = search(
            db, cfg, query="kubernetis autoscaller", owner_id=owner, search_mode="fuzzy"
        )
        assert r["results"][0]["node_id"] == ids[texts[2]]

        r = search(
            db, cfg, query="billing database", owner_id=owner, search_mode="hybrid"
        )
        assert r["results"][0]["node_id"] == ids[texts[1]]
        assert "score" in r["results"][0]

        # A write must be visible to the cached lexical index.
        new = create_node(
            db, cfg, text="Zebra migration finished", owner_id=owner, auto_link=False
        )
        r = search(db, cfg, query="zebra", owner_id=owner, search_mode="bm25")
        assert [x["node_id"] for x in r["results"]] == [new["node"]["node_id"]]

        bad = search(db, cfg, query="x", owner_id=owner, search_mode="nope")
        assert bad["success"] is False
    finally:
        db.delete_owner_graph(owner)


@pytest.mark.nodb
def test_reranker_orders_relevant_first():
    """Cross-encoder puts the on-topic text first (skips if the model is unavailable)."""
    from graph_memory_mcp.graph_memory import reranker

    try:
        reranker.load_reranker(None)
    except Exception as exc:  # offline CI, no cached model
        pytest.skip(f"reranker model unavailable: {exc}")
    results = [
        {"node_id": "a", "text": "The cafeteria serves lunch at noon."},
        {"node_id": "b", "text": "Postgres was upgraded to version 16 in March."},
    ]
    out = reranker.rerank(
        "which postgres version do we run",
        results,
        model_name=None,
        top_k=10,
        strategy="replace",
    )
    assert out[0]["node_id"] == "b"
    assert "rerank_score" in out[0]


@pytest.mark.nodb
def test_rerank_strategies_without_model():
    """RRF/protect fuse first-stage order with CE scores; no ONNX load."""
    from graph_memory_mcp.graph_memory.reranker import (
        apply_strategy,
        normalize_rerank_strategy,
        rerank,
    )

    assert normalize_rerank_strategy(None) == "gated"
    assert normalize_rerank_strategy("replace") == "replace"
    with pytest.raises(ValueError):
        normalize_rerank_strategy("magic")

    # First-stage order prefers a; CE prefers b.
    head = [
        {"node_id": "a", "text": "Ticket OPS-48200 was closed after a cache fix."},
        {"node_id": "b", "text": "The cafeteria serves lunch at noon."},
        {"node_id": "c", "text": "Unrelated note about weather."},
    ]
    # CE wants b first, then c, then a (would demote the ticket).
    scores = [-5.0, 9.0, 1.0]
    replaced = apply_strategy("OPS-48200 cache", head, scores, strategy="replace")
    assert [r["node_id"] for r in replaced] == ["b", "c", "a"]

    # Clear CE margin (>= 2.0): gated follows CE.
    gated_clear = apply_strategy(
        "OPS-48200 cache", head, scores, strategy="gated", gate_margin=2.0
    )
    assert [r["node_id"] for r in gated_clear] == ["b", "c", "a"]
    assert gated_clear[0]["rerank_gated"] is True

    # Flat CE scores: gated keeps first-stage order.
    flat = [0.1, 0.2, 0.15]
    gated_flat = apply_strategy(
        "OPS-48200 cache", head, flat, strategy="gated", gate_margin=2.0
    )
    assert [r["node_id"] for r in gated_flat] == ["a", "b", "c"]
    assert gated_flat[0]["rerank_gated"] is False

    rrfd = apply_strategy("OPS-48200 cache", head, scores, strategy="rrf")
    # a keeps first-stage credit so it should not fall to last.
    assert rrfd[0]["node_id"] in ("a", "b")
    assert "rerank_fuse" in rrfd[0]

    protected = apply_strategy("OPS-48200 cache", head, scores, strategy="protect")
    assert protected[0]["node_id"] == "a"

    # Public API accepts injected scores (unit-test path).
    out = rerank(
        "OPS-48200 cache",
        head,
        model_name=None,
        top_k=10,
        strategy="protect",
        scores=scores,
    )
    assert out[0]["node_id"] == "a"
    assert out[0]["rerank_score"] == -5.0


@pytest.mark.nodb
def test_rerank_strategy_config_default():
    from graph_memory_mcp.config import MCPServerConfig

    cfg = MCPServerConfig()
    assert cfg.search_reranker_enabled is False
    assert cfg.search_rerank_strategy == "gated"
    assert cfg.default_search_mode == "embedding"


@pytest.mark.nodb
def test_rerank_skip_and_small_pool_keep_tail():
    from graph_memory_mcp.graph_memory.reranker import rerank, should_skip

    rows = [
        {"node_id": n, "text": n, "similarity": s}
        for n, s in [("a", 0.90), ("b", 0.80), ("c", 0.79), ("d", 0.70)]
    ]
    assert should_skip(rows, 0.05)
    assert not should_skip(rows, 0.0)
    assert not should_skip([{"node_id": "x"}, {"node_id": "y"}], 0.05)
    # Skip returns the same list without loading the model.
    assert (
        rerank("q", rows, model_name="no/such-model", top_k=2, skip_sim_gap=0.05)
        is rows
    )
    # Small pool reorders only the head; tail kept in order, nothing dropped.
    out = rerank(
        "q", rows, model_name=None, top_k=2, strategy="replace", scores=[0.0, 5.0]
    )
    assert [r["node_id"] for r in out] == ["b", "a", "c", "d"]


@pytest.mark.nodb
def test_rerank_speed_config_defaults():
    from graph_memory_mcp.config import MCPServerConfig

    cfg = MCPServerConfig()
    assert cfg.search_reranker_threads == 2
    assert cfg.search_rerank_skip_sim_gap == 0.0
    assert cfg.search_rerank_top_k == 10


@pytest.mark.nodb
def test_rerank_top10_keeps_tail_with_large_limit():
    """With 25 candidates and top_k=10, only the head is reordered."""
    from graph_memory_mcp.graph_memory.reranker import rerank

    rows = [{"node_id": f"n{i:02d}", "text": f"t{i}"} for i in range(25)]
    scores = [float(i) for i in range(10)]  # CE prefers the 10th head item
    out = rerank("q", rows, model_name=None, top_k=10, strategy="gated", scores=scores)
    assert len(out) == 25
    assert sorted(r["node_id"] for r in out[:10]) == [f"n{i:02d}" for i in range(10)]
    assert [r["node_id"] for r in out[10:]] == [f"n{i:02d}" for i in range(10, 25)]
    assert all("rerank_score" not in r for r in out[10:])
