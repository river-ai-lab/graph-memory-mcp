#!/usr/bin/env python3
"""Offline reranker-strategy comparison (no graph DB).

Ranks Scenario 1 fact texts with the local embedding model and in-memory BM25,
then applies cross-encoder strategies (replace / rrf / protect). Label results
as offline evaluation — not a FalkorDB/ArcadeDB run.

  uv run python tests/benchmarks/search_modes/rerank_offline.py
  uv run python tests/benchmarks/search_modes/rerank_offline.py --noise 1000
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from generate import build  # noqa: E402
from run import probe_sets  # noqa: E402

CAND = 30
LIMIT = 100


def _mrr_r5(ranked_ids: list[str], gold: list[str]) -> tuple[float, float]:
    gold_s = set(gold)
    rr = 0.0
    for rank, fid in enumerate(ranked_ids, start=1):
        if fid in gold_s:
            rr = 1.0 / rank
            break
    r5 = len(set(ranked_ids[:5]) & gold_s) / len(gold_s)
    return rr, r5


def _embed_rank(
    qvec: np.ndarray, ids: list[str], mat: np.ndarray, limit: int
) -> list[str]:
    sims = mat @ qvec
    order = np.argsort(-sims)[:limit]
    return [ids[i] for i in order]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--noise", type=int, default=1000)
    ap.add_argument("--out", default=str(HERE / "results_rerank_offline.json"))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    from graph_memory_mcp.config import load_mcp_server_config
    from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService
    from graph_memory_mcp.graph_memory.lexical_search import LexicalIndex, rrf_fuse
    from graph_memory_mcp.graph_memory.reranker import (
        apply_strategy,
        load_reranker,
    )

    data = build()
    typo, ident, ident_facts = probe_sets(data["core"]["facts"])
    rng = random.Random(args.seed)
    # Held-out: odd question ids for reporting; even for informal tuning notes.
    s1 = list(data["questions"])
    holdout = [q for q in s1 if int(q["id"][1:]) % 2 == 1]
    tune = [q for q in s1 if int(q["id"][1:]) % 2 == 0]

    # A few agent-style paraphrases over core facts (not in S1 wording).
    agent = []
    samples = rng.sample(
        [f for f in data["core"]["facts"] if f["status"] == "active"], 8
    )
    for i, f in enumerate(samples):
        words = f["text"].rstrip(".").split()
        # Drop the template verb-ish middle; keep entities.
        q = "remember: " + " ".join(w for w in words if w[:1].isupper() or "-" in w)
        if len(q.split()) < 3:
            q = "what do we know about " + words[0]
        agent.append({"id": f"a{i:02d}", "type": "agent", "q": q, "gold": [f["id"]]})

    # Tiny RU probes: transliterate-style agent queries over English facts.
    # The English CE is not expected to shine; reported for honesty.
    ru = []
    for i, f in enumerate(samples[:4]):
        name = f["text"].split()[0]
        ru.append(
            {
                "id": f"r{i:02d}",
                "type": "ru",
                "q": f"что известно про {name}",
                "gold": [f["id"]],
            }
        )

    facts = [f for f in data["core"]["facts"] + ident_facts if f["status"] == "active"]
    if args.noise:
        facts = facts + data["noise"]["facts"][: args.noise]

    cfg = load_mcp_server_config()
    emb = EmbeddingService(
        cfg.embedding_model,
        query_prefix=cfg.embedding_query_prefix,
        passage_prefix=cfg.embedding_passage_prefix,
        backend=cfg.embedding_backend,
    )
    texts = [f["text"] for f in facts]
    ids = [f["id"] for f in facts]
    t0 = time.perf_counter()
    mat = np.asarray(emb.get_embeddings_batch(texts, kind="passage"), dtype=np.float32)
    # Row-normalize for cosine via dot product.
    mat /= np.clip(np.linalg.norm(mat, axis=1, keepdims=True), 1e-9, None)
    embed_ms = (time.perf_counter() - t0) * 1000
    print(f"embedded {len(facts)} facts in {embed_ms:.0f} ms", flush=True)

    rows_lex = [
        [fid, "Fact", text, None, 1, "{}", 0.0] for fid, text in zip(ids, texts)
    ]
    lex = LexicalIndex.build(rows_lex)
    ce = load_reranker(None)
    by_text = dict(zip(ids, texts))

    def first_stage(query: str, mode: str) -> list[dict]:
        if mode == "embedding":
            qv = np.asarray(emb.get_embedding(query, kind="query"), dtype=np.float32)
            qv = qv / max(float(np.linalg.norm(qv)), 1e-9)
            ranked = _embed_rank(qv, ids, mat, LIMIT)
        elif mode == "bm25":
            ranked = [row[0] for row, _ in lex.search(query, "bm25", LIMIT)]
        elif mode == "hybrid":
            qv = np.asarray(emb.get_embedding(query, kind="query"), dtype=np.float32)
            qv = qv / max(float(np.linalg.norm(qv)), 1e-9)
            emb_ids = _embed_rank(qv, ids, mat, LIMIT)
            bm_ids = [row[0] for row, _ in lex.search(query, "bm25", LIMIT)]
            fused = rrf_fuse([emb_ids, bm_ids])
            ranked = sorted(fused, key=lambda x: (-fused[x], x))[:LIMIT]
        else:
            raise ValueError(mode)
        return [{"node_id": fid, "text": by_text[fid]} for fid in ranked]

    strategies = ("none", "replace", "rrf", "protect", "gated")
    bases = ("embedding", "hybrid")
    groups = {
        "tune": tune,
        "holdout": holdout,
        "scenario1": s1,
        "typo": typo,
        "ident": ident,
        "agent": agent,
        "ru": ru,
    }

    results = {
        "label": "offline_no_db",
        "noise": args.noise,
        "candidate_top_k": CAND,
        "model": "Xenova/ms-marco-MiniLM-L-6-v2",
        "embed_ms": round(embed_ms, 1),
        "n_facts": len(facts),
        "systems": {},
    }

    for base in bases:
        for strategy in strategies:
            name = base if strategy == "none" else f"{base}+{strategy}"
            latencies = []
            group_rows = {g: [] for g in groups}
            for gname, questions in groups.items():
                for q in questions:
                    t = time.perf_counter()
                    cand = first_stage(q["q"], base)
                    if strategy == "none":
                        ranked = cand
                    else:
                        head = cand[:CAND]
                        scores = ce.score(q["q"], [r["text"] for r in head])
                        ranked = (
                            apply_strategy(
                                q["q"],
                                head,
                                scores,
                                strategy=strategy,
                                gate_margin=2.0,
                            )
                            + cand[CAND:]
                        )
                    latencies.append((time.perf_counter() - t) * 1000)
                    ranked_ids = [r["node_id"] for r in ranked]
                    mrr, r5 = _mrr_r5(ranked_ids, q["gold"])
                    group_rows[gname].append({"mrr": mrr, "r@5": r5})
            agg = {}
            for gname, rows in group_rows.items():
                if not rows:
                    continue
                agg[gname] = {
                    "n": len(rows),
                    "mrr": round(sum(r["mrr"] for r in rows) / len(rows), 3),
                    "r@5": round(sum(r["r@5"] for r in rows) / len(rows), 3),
                }
            med_lat = round(statistics.median(latencies), 1) if latencies else None
            results["systems"][name] = {"agg": agg, "latency_ms_median": med_lat}
            s1a = agg["scenario1"]
            print(
                f"{name:28s} S1 mrr={s1a['mrr']} r@5={s1a['r@5']} "
                f"holdout mrr={agg['holdout']['mrr']} typo mrr={agg['typo']['mrr']} "
                f"agent mrr={agg['agent']['mrr']} lat={med_lat}ms",
                flush=True,
            )

    Path(args.out).write_text(json.dumps(results, indent=1) + "\n")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
