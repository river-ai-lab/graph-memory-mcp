"""Hybrid rank and contradiction-pair hints. No FalkorDB."""

from graph_memory_mcp.graph_memory.compact_recall import decorate_search_response
from graph_memory_mcp.graph_memory.search_rank import hard_tokens, rerank_results


def test_hard_tokens_skip_bare_years():
    tokens = [
        token.lower()
        for token in hard_tokens("шаг 3 голова 16 2012 48Gi _is_winter_stages")
    ]
    assert "48gi" in tokens
    assert "_is_winter_stages" in tokens
    assert "2012" not in tokens
    assert "16" not in tokens


def test_identifier_outranks_higher_cosine():
    now = 1_700_000_000_000
    old = {
        "node_id": "old",
        "text": "CatBoost USDA windows 2010 2011 2012 2013 2014 2015",
        "similarity": 0.90,
        "created_at": now - 400 * 86_400_000,
    }
    fresh = {
        "node_id": "new",
        "text": "head 16 rerun with 48Gi after the 24Gi job died",
        "similarity": 0.78,
        "created_at": now,
    }
    ranked = rerank_results(
        [old, fresh],
        query="head 16 2012 48Gi",
        now_ms=now,
        lexical_weight=0.35,
        recency_weight=0.10,
        half_life_days=14,
    )
    assert ranked[0]["node_id"] == "new"
    assert ranked[0]["lexical"] == 1.0
    assert ranked[1]["lexical"] == 0.0


def test_symbol_and_run_id_match():
    now = 1_700_000_000_000
    ranked = rerank_results(
        [
            {
                "node_id": "vague",
                "text": "spring wheat stages and GDD season",
                "similarity": 0.91,
                "created_at": now,
            },
            {
                "node_id": "exact",
                "text": "winter_season is chosen by _is_winter_stages not the word Jointing",
                "similarity": 0.72,
                "created_at": now,
            },
        ],
        query="Jointing bug _is_winter_stages",
        now_ms=now,
        lexical_weight=0.35,
        recency_weight=0.10,
        half_life_days=14,
    )
    assert ranked[0]["node_id"] == "exact"


def test_contradiction_pair_leads_suggested_next():
    payload = {
        "success": True,
        "results": [
            {
                "node_id": "a",
                "node_type": "Fact",
                "text": "USDA stages are in the window",
                "similarity": 0.8,
            },
            {
                "node_id": "b",
                "node_type": "Fact",
                "text": "claim year has no USDA stages",
                "similarity": 0.7,
            },
        ],
        "facts": [],
        "entities": [],
        "contradiction_pairs": [
            {"from_id": "a", "to_id": "b", "relation_type": "CONTRADICTS"}
        ],
    }
    out = decorate_search_response(
        payload,
        compact=False,
        snippet_chars=180,
        token_budget=800,
        query="USDA windows",
        owner_id="luminaria",
    )
    assert out["contradiction_pairs"][0]["relation_type"] == "CONTRADICTS"
    assert "get_trace" in out["suggested_next"][0]
    assert "mark_outdated" in out["suggested_next"][1]
