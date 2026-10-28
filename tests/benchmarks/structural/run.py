#!/usr/bin/env python3
"""Structural retrieval benchmark: graph search, graph recall_context, plain RAG.

No chat LLM. Embeddings are the server's local ONNX model for every system.
Tokens are counted with a fixed regex proxy: one token per \\w+ run or per
punctuation char (no tokenizer dependency). Run against FalkorDB:

  GRAPH_BACKEND=falkordb python tests/benchmarks/structural/run.py

Noise levels are nested (0, then +1k, then +9k) on one owner. Each finished
(level, system) cell is checkpointed to --checkpoint so a rerun resumes.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
BUDGETS = (200, 500, 1000)
LEVELS = (0, 1000, 10000)
TOKEN_RE = re.compile(r"\w+|[^\w\s]")
OWNER = "structbench"

logging.basicConfig(level=logging.ERROR)


def ntok(text: str) -> int:
    return len(TOKEN_RE.findall(text))


class Store:
    def __init__(self, server, data: dict) -> None:
        self.s = server
        self.data = data
        self.uid: dict[str, str] = {}  # dataset id -> node uid
        self.rev: dict[str, str] = {}
        self.loaded = 0
        self.rag_ids: list[str] = []
        self.rag_text: list[str] = []
        self.rag_vecs: list[np.ndarray] = []
        self.notes: list[str] = []

    def reset(self) -> None:
        self.s.db_client.delete_owner_graph(OWNER)

    def _bulk(self, items: list[dict], node_type: str) -> None:
        for i in range(0, len(items), 200):
            chunk = items[i : i + 200]
            r = self.s.create_nodes(
                items=[
                    {"text": x["text"], "metadata": {"bench_id": x["id"]}}
                    for x in chunk
                ],
                node_type=node_type,
                owner_id=OWNER,
            )
            if not r.get("success", True):
                raise RuntimeError(r)
            for x, n in zip(chunk, r["nodes"]):
                self.uid[x["id"]] = n["node_id"]
                self.rev[n["node_id"]] = x["id"]

    def add(self, facts: list[dict], entities: list[dict], edges: list[dict]) -> None:
        new_ents = [e for e in entities if e["id"] not in self.uid]
        self._bulk(new_ents, "Entity")
        self._bulk(facts, "Fact")
        for f in facts:
            if f["status"] == "outdated":
                r = self.s.mark_outdated(
                    fact_id=self.uid[f["id"]], reason="superseded", owner_id=OWNER
                )
                if not r.get("success", True):
                    self.notes.append(f"mark_outdated {f['id']}: {r}")
        for e in edges:
            a, b = self.uid.get(e["from"]), self.uid.get(e["to"])
            if not a or not b:
                continue
            r = self.s.create_relation(
                from_id=a, to_id=b, relation_type=e["type"], owner_id=OWNER
            )
            if not r.get("success", True):
                self.notes.append(f"relation {e}: {r.get('error')}")
        vecs = []
        for i in range(0, len(facts), 128):
            vecs += self.s.embedding_service.get_embeddings_batch(
                [f["text"] for f in facts[i : i + 128]]
            )
        self.rag_ids += [f["id"] for f in facts]
        self.rag_text += [f["text"] for f in facts]
        self.rag_vecs += [np.asarray(v, dtype=np.float32) for v in vecs]


def ctx_rag(st: Store, q: str) -> list[tuple[str, str]]:
    qv = np.asarray(
        st.s.embedding_service.get_embedding(q, kind="query"), dtype=np.float32
    )
    sims = np.stack(st.rag_vecs) @ qv
    order = np.argsort(-sims, kind="stable")[:100]
    return [(st.rag_ids[i], st.rag_text[i]) for i in order]


def ctx_search(st: Store, q: str) -> list[tuple[str, str]]:
    r = st.s.search(query=q, owner_id=OWNER, limit=100, node_types=["Fact"])
    return [
        (st.rev.get(x["node_id"], "?"), x.get("text") or "")
        for x in r.get("results") or []
    ]


def make_recall(depth: int):
    def ctx(st: Store, q: str) -> list[tuple[str, str]]:
        r = st.s.recall_context(
            query=q, owner_id=OWNER, depth=depth, limit=5, max_nodes=50
        )
        if not r.get("success", True):
            raise RuntimeError(r)
        return [
            (st.rev.get(n["node_id"], "?"), n.get("text") or "")
            for n in r.get("nodes") or []
        ]

    return ctx


SYSTEMS = {
    "rag": ctx_rag,
    "graph_search": ctx_search,
    "graph_recall_d2": make_recall(2),
    "graph_recall_d3": make_recall(3),
}


def score(ctx: list[tuple[str, str]], q: dict) -> dict:
    gold = set(q["gold"])
    stale = set(q.get("stale") or [])
    cum, found, all_at, stale_at = 0, {}, None, None
    for fid, text in ctx:
        cum += ntok(text)
        if fid in gold and fid not in found:
            found[fid] = cum
            if len(found) == len(gold):
                all_at = cum
        if fid in stale and stale_at is None:
            stale_at = cum
    out = {"tokens_all_gold": all_at, "total_tokens": cum, "n_items": len(ctx)}
    for b in BUDGETS:
        out[f"recall@{b}"] = sum(1 for t in found.values() if t <= b) / len(gold)
        out[f"all@{b}"] = float(all_at is not None and all_at <= b)
        out[f"stale@{b}"] = (
            float(stale_at is not None and stale_at <= b) if stale else None
        )
    out["answer_found@1000"] = (
        float(q["answer_fact"] in found and found[q["answer_fact"]] <= 1000)
        if "answer_fact" in q
        else None
    )
    return out


def aggregate(rows: list[dict]) -> dict:
    agg: dict = {"n": len(rows)}
    keys = [
        k
        for k in rows[0]
        if k.startswith(("recall@", "all@", "stale@", "answer_found"))
    ]
    for k in keys:
        vals = [r[k] for r in rows if r[k] is not None]
        if vals:
            agg[k] = round(sum(vals) / len(vals), 3)
    toks = [r["tokens_all_gold"] for r in rows if r["tokens_all_gold"] is not None]
    agg["all_gold_found"] = f"{len(toks)}/{len(rows)}"
    agg["median_tokens_all_gold"] = statistics.median(toks) if toks else None
    agg["latency_ms_median"] = round(
        statistics.median(r["latency_ms"] for r in rows), 1
    )
    return agg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(HERE / "dataset.json"))
    ap.add_argument("--out", default=str(HERE.parent / "results_structural.json"))
    ap.add_argument("--checkpoint", default="/tmp/structural_checkpoint.json")
    ap.add_argument("--levels", default=",".join(map(str, LEVELS)))
    args = ap.parse_args()
    data = json.loads(Path(args.dataset).read_text())
    sys.path.insert(0, str(HERE))
    from generate import build

    full = build()
    if full["core"] != data["core"] or full["questions"] != data["questions"]:
        raise SystemExit("dataset.json is stale: run generate.py")
    data["noise"] = full["noise"]
    levels = [int(x) for x in args.levels.split(",")]

    from graph_memory_mcp.config import load_mcp_server_config
    from graph_memory_mcp.server import GraphMemoryMCP

    cfg = load_mcp_server_config()
    server = GraphMemoryMCP(cfg)
    st = Store(server, data)
    st.reset()
    results: dict = {
        "backend": cfg.graph_backend if hasattr(cfg, "graph_backend") else "?",
        "tokenizer": "regex \\w+|[^\\w\\s]",
        "budgets": BUDGETS,
        "levels": {},
    }
    core, noise = data["core"], data["noise"]
    ingest_s = {}
    prev = 0
    for lvl in levels:
        t0 = time.time()
        if lvl == 0 or prev == 0 and not st.uid:
            st.add(core["facts"], core["entities"], core["edges"])
        if lvl > prev:
            facts = noise["facts"][prev:lvl]
            ids = {f["id"] for f in facts}
            ments = {e for f in facts for e in f["entities"]}
            ents = [e for e in noise["entities"] if e["id"] in ments]
            known = set(st.uid) | ids | ments
            edges = [
                e
                for e in noise["edges"]
                if (
                    e["from"] in ids
                    or e["to"] in ids
                    or (e["from"] in ments and e["to"] in ments)
                )
                and e["from"] in known
                and e["to"] in known
            ]
            st.add(facts, ents, edges)
        prev = lvl
        ingest_s[lvl] = round(time.time() - t0, 1)
        print(
            f"level {lvl}: ingested in {ingest_s[lvl]}s, notes={len(st.notes)}",
            flush=True,
        )
        level_out: dict = {"ingest_s": ingest_s[lvl], "systems": {}}
        for name, fn in SYSTEMS.items():
            fn(st, "warm up query")
            rows = []
            for q in data["questions"]:
                t = time.perf_counter()
                ctx = fn(st, q["q"])
                lat = (time.perf_counter() - t) * 1000
                r = score(ctx, q)
                r.update(id=q["id"], type=q["type"], latency_ms=lat)
                rows.append(r)
            by_type = {}
            for typ in sorted({r["type"] for r in rows}):
                by_type[typ] = aggregate([r for r in rows if r["type"] == typ])
            by_type["all"] = aggregate(rows)
            level_out["systems"][name] = {"by_type": by_type, "rows": rows}
            print(f"  {name}: all@1000={by_type['all'].get('all@1000')}", flush=True)
        results["levels"][str(lvl)] = level_out
        results["notes"] = st.notes[:50]
        Path(args.checkpoint).write_text(json.dumps(results, indent=1, default=str))
    Path(args.out).write_text(json.dumps(results, indent=1, default=str) + "\n")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
