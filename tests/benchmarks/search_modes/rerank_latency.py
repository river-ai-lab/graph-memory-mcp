"""Offline end-to-end latency (query embedding + rerank, no DB) for rerank configs."""

import statistics
import sys
import time

import numpy as np

sys.path.insert(0, "tests/benchmarks/search_modes")
from generate import build

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService
from graph_memory_mcp.graph_memory.reranker import rerank

d = build()
facts = d["core"]["facts"] + d["noise"]["facts"][:1000]
cfg = load_mcp_server_config()
e = EmbeddingService(
    cfg.embedding_model,
    query_prefix=cfg.embedding_query_prefix,
    passage_prefix=cfg.embedding_passage_prefix,
    backend=cfg.embedding_backend,
)
tx = [f["text"] for f in facts]
M = np.asarray(e.get_embeddings_batch(tx, kind="passage"), np.float32)
M /= np.linalg.norm(M, axis=1, keepdims=True)
qs = [q["q"] for q in d["questions"]]


def run(K, th, skip, on=True):
    lat = []
    for rep in range(4):
        for q in qs:
            t = time.perf_counter()
            v = np.asarray(e.get_embedding(q, kind="query"), np.float32)
            v /= np.linalg.norm(v)
            s = M @ v
            o = np.argsort(-s)[:100]
            res = [
                {"node_id": str(j), "text": tx[j], "similarity": float(s[j])} for j in o
            ]
            if on:
                rerank(
                    q,
                    res,
                    model_name=None,
                    top_k=K,
                    strategy="gated",
                    threads=th,
                    skip_sim_gap=skip,
                )
            if rep:
                lat.append((time.perf_counter() - t) * 1000)
    lat.sort()
    return (
        round(statistics.median(lat), 1),
        round(lat[int(0.95 * len(lat)) - 1], 1),
        len(lat),
    )


print("off", run(30, 2, 0, False))
for K, th, sk in [(30, 2, 0), (10, 2, 0), (10, 4, 0), (10, 2, 0.02), (10, 4, 0.02)]:
    print(f"K={K} threads={th} skip={sk}", run(K, th, sk))
