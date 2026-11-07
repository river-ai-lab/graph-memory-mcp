"""Offline (no DB) warmed check of the selected rerank config: gated, top 10, 2 threads, no skip."""

import statistics
import sys
import time

import numpy as np

sys.path.insert(0, "tests/benchmarks/search_modes")
from generate import build
from run import probe_sets

from graph_memory_mcp.config import MCPServerConfig, load_mcp_server_config
from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService
from graph_memory_mcp.graph_memory.reranker import rerank

c = MCPServerConfig()
print(
    "config",
    c.search_reranker_enabled,
    c.search_rerank_top_k,
    c.search_rerank_strategy,
    c.search_reranker_threads,
    c.search_rerank_skip_sim_gap,
    c.default_search_mode,
)
d = build()
ty, idn, idf = probe_sets(d["core"]["facts"])
s1 = d["questions"]
facts = [f for f in d["core"]["facts"] + idf if f["status"] == "active"] + d["noise"][
    "facts"
][:1000]
cfg = load_mcp_server_config()
e = EmbeddingService(
    cfg.embedding_model,
    query_prefix=cfg.embedding_query_prefix,
    passage_prefix=cfg.embedding_passage_prefix,
    backend=cfg.embedding_backend,
)
ids = [f["id"] for f in facts]
tx = [f["text"] for f in facts]
M = np.asarray(e.get_embeddings_batch(tx, kind="passage"), np.float32)
M /= np.linalg.norm(M, axis=1, keepdims=True)
sets = {
    "s1": s1,
    "holdout": [q for q in s1 if int(q["id"][1:]) % 2],
    "typo": ty,
    "ident": idn,
}


def go(K):
    res = {}
    lat = []
    tail_ok = True
    for rep in range(3):
        for n, qs in sets.items():
            m = []
            r5 = []
            for q in qs:
                t = time.perf_counter()
                v = np.asarray(e.get_embedding(q["q"], kind="query"), np.float32)
                v /= np.linalg.norm(v)
                s = M @ v
                o = np.argsort(-s)[:100]
                rows = [
                    {"node_id": ids[j], "text": tx[j], "similarity": float(s[j])}
                    for j in o
                ]
                out = (
                    rows
                    if K == 0
                    else rerank(
                        q["q"],
                        rows,
                        model_name=None,
                        top_k=K,
                        strategy="gated",
                        threads=2,
                        skip_sim_gap=0,
                    )
                )
                if rep:
                    lat.append((time.perf_counter() - t) * 1000)
                if K and [x["node_id"] for x in out[K:]] != [
                    x["node_id"] for x in rows[K:]
                ]:
                    tail_ok = False
                order = [x["node_id"] for x in out]
                g = set(q["gold"])
                m.append(next((1 / i for i, x in enumerate(order, 1) if x in g), 0))
                r5.append(len(set(order[:5]) & g) / len(g))
            res[n] = (round(sum(m) / len(m), 3), round(sum(r5) / len(r5), 3))
    lat.sort()
    return (
        res,
        round(statistics.median(lat), 1),
        round(lat[int(0.95 * len(lat)) - 1], 1),
        len(lat),
        tail_ok,
    )


for K in (0, 10, 30):
    print("off" if K == 0 else f"gated top{K}", *go(K))
