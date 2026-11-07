"""Offline CE profiling (no DB): cold load, per-call latency by pool size and threads."""

import statistics
import sys
import time

sys.path.insert(0, "tests/benchmarks/search_modes")
import onnxruntime as ort
from generate import build

from graph_memory_mcp.graph_memory import reranker as R

d = build()
texts = [f["text"] for f in d["core"]["facts"] + d["noise"]["facts"][:200]]
qs = [q["q"] for q in d["questions"]]
t = time.perf_counter()
ce = R.load_reranker(None)
print("cold load ms", round((time.perf_counter() - t) * 1000))
t = time.perf_counter()
ce.score(qs[0], texts[:30])
print("first inference ms", round((time.perf_counter() - t) * 1000))
enc = ce._tokenizer.encode_batch([(qs[0], x) for x in texts[:30]])
print("seq len", len(enc[0].ids))


def bench(threads, k):
    if threads is not None:
        o = ort.SessionOptions()
        o.intra_op_num_threads = threads
        ce._session = ort.InferenceSession(
            ce._session._model_path, sess_options=o, providers=["CPUExecutionProvider"]
        )
    ce.score(qs[0], texts[:k])
    lat = []
    for i in range(3):
        for q in qs:
            t = time.perf_counter()
            ce.score(q, texts[i * 30 : i * 30 + k])
            lat.append((time.perf_counter() - t) * 1000)
    lat.sort()
    return (
        round(statistics.median(lat), 1),
        round(lat[int(0.95 * len(lat))], 1),
        len(lat),
    )


for th in (2, 4, 8):
    for k in (5, 10, 20, 30):
        print("threads", th, "k", k, "median/p95/n", bench(th if k == 5 else None, k))
