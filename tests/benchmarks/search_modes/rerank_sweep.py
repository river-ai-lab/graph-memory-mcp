"""Offline quality sweep (no DB): gated rerank pool size and pre-inference skip."""

import random
import sys

import numpy as np

sys.path.insert(0, "tests/benchmarks/search_modes")
from generate import build
from run import probe_sets

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService
from graph_memory_mcp.graph_memory.reranker import apply_strategy, load_reranker

d = build()
typo, ident, idf = probe_sets(d["core"]["facts"])
s1 = d["questions"]
hold = [q for q in s1 if int(q["id"][1:]) % 2]
rng = random.Random(42)
smp = rng.sample([f for f in d["core"]["facts"] if f["status"] == "active"], 12)
agent = [
    {
        "q": "remember: "
        + " ".join(w for w in f["text"].rstrip(".").split() if w[:1].isupper()),
        "gold": [f["id"]],
    }
    for f in smp
]
ru = [
    {
        "q": "что известно про " + f["text"].split()[0] + " " + f["text"].split()[1],
        "gold": [f["id"]],
    }
    for f in smp[:8]
]
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
ce = load_reranker(None)
sets = {"s1": s1, "hold": hold, "agent": agent, "typo": typo, "ident": ident, "ru": ru}
pre = {}
for n, qs in sets.items():
    for i, q in enumerate(qs):
        v = np.asarray(e.get_embedding(q["q"], kind="query"), np.float32)
        v /= np.linalg.norm(v)
        s = M @ v
        o = np.argsort(-s)[:100]
        sc = ce.score(q["q"], [tx[j] for j in o[:30]])
        pre[(n, i)] = (o, s[o], sc, q["gold"])


def mrr(order, g):
    for r, x in enumerate(order, 1):
        if x in g:
            return 1 / r
    return 0


def run(K, skip):
    out = {}
    calls = 0
    tot = 0
    for n, qs in sets.items():
        v = []
        for i, q in enumerate(qs):
            o, sim, sc, g = pre[(n, i)]
            order = [ids[j] for j in o]
            tot += 1
            if skip is not None and sim[0] - sim[1] >= skip:
                v.append(mrr(order, g))
                continue
            calls += 1
            head = [{"node_id": x} for x in order[:K]]
            r = [
                h["node_id"]
                for h in apply_strategy(q["q"], head, sc[:K], strategy="gated")
            ]
            v.append(mrr(r + order[K:], g))
        out[n] = round(sum(v) / len(v), 3)
    return out, f"{calls}/{tot}"


print(
    "baseline",
    {
        n: round(
            sum(
                mrr([ids[j] for j in pre[(n, i)][0]], q["gold"])
                for i, q in enumerate(qs)
            )
            / len(qs),
            3,
        )
        for n, qs in sets.items()
    },
)
for K in (5, 10, 20, 30):
    for skip in (None, 0.02, 0.04):
        print("K", K, "skip", skip, *run(K, skip))
gaps = sorted(round(float(pre[k][1][0] - pre[k][1][1]), 3) for k in pre)
print("sim gap quantiles", gaps[:: len(gaps) // 10])
