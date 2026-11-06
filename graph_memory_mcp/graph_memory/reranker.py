"""Optional cross-encoder reranker (ONNX Runtime, no PyTorch).

Off by default. ``SEARCH_RERANKER_MODEL`` names a Hugging Face repo with
``onnx/model.onnx`` and ``tokenizer.json`` (default
``Xenova/ms-marco-MiniLM-L-6-v2``, about 90 MB, English). The model scores
(query, text) pairs; the top ``SEARCH_RERANK_TOP_K`` results are reordered.

Strategies (``SEARCH_RERANK_STRATEGY``):

* ``gated`` — if the top two cross-encoder scores differ by at least
  ``SEARCH_RERANK_GATE_MARGIN``, use the CE order; otherwise keep the
  first-stage order (default). Helps ordinary queries without demoting
  results when the CE is unsure (for example typo-heavy queries).
* ``replace`` — sort only by cross-encoder score.
* ``rrf`` — Reciprocal Rank Fusion of the first-stage order and the CE order.
* ``protect`` — like ``rrf``, plus a third list of strong exact/identifier
  matches so ticket ids and quoted phrases are not demoted by CE noise.

Uses the same runtime and download helpers as the embedding backend.
"""

from __future__ import annotations

import re
import threading
from typing import Dict, List, Optional, Sequence

import numpy as np

from graph_memory_mcp.graph_memory.embedding_backend import (
    _download_required,
    _import_onnxruntime,
    _load_tokenizer,
    _ort_int_dtype,
)
from graph_memory_mcp.graph_memory.lexical_search import (
    normalize_phrase,
    rrf_fuse,
    tokenize,
)

DEFAULT_RERANKER_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
RERANK_STRATEGIES = ("gated", "replace", "rrf", "protect")
DEFAULT_RERANK_STRATEGY = "gated"
DEFAULT_RRF_K = 60
DEFAULT_GATE_MARGIN = 2.0
_LOCK = threading.Lock()
_LOADED: Dict[str, "CrossEncoderReranker"] = {}
_MAX_LEN = 256
_BATCH = 32
# Token looks like an identifier agents quote: OPS-48200, RUN_…, gpu-7, …
_IDENT = re.compile(r"(?i)(?=.*[\d_])[a-z0-9][a-z0-9._/-]{2,}")


def normalize_rerank_strategy(value: Optional[str]) -> str:
    if value is None or not str(value).strip():
        return DEFAULT_RERANK_STRATEGY
    strategy = str(value).strip().lower().replace("-", "_")
    aliases = {
        "ce": "replace",
        "cross_encoder": "replace",
        "pure": "replace",
        "gate": "gated",
        "margin": "gated",
    }
    strategy = aliases.get(strategy, strategy)
    if strategy not in RERANK_STRATEGIES:
        raise ValueError(
            f"Invalid search_rerank_strategy {value!r}; "
            f"expected one of {', '.join(RERANK_STRATEGIES)}"
        )
    return strategy


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        ort = _import_onnxruntime()
        self.model_name = model_name
        self._tokenizer = _load_tokenizer(model_name)
        self._tokenizer.enable_truncation(_MAX_LEN)
        path = _download_required(model_name, "onnx/model.onnx")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        self._session = ort.InferenceSession(
            path, sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self._inputs = list(self._session.get_inputs())

    def score(self, query: str, texts: List[str]) -> np.ndarray:
        out: List[float] = []
        for start in range(0, len(texts), _BATCH):
            chunk = texts[start : start + _BATCH]
            enc = self._tokenizer.encode_batch([(query, t or "") for t in chunk])
            ids = np.asarray([e.ids for e in enc])
            mask = np.asarray([e.attention_mask for e in enc])
            types = np.asarray([e.type_ids for e in enc])
            feed = {}
            for spec in self._inputs:
                dtype = _ort_int_dtype(spec.type)
                src = {
                    "input_ids": ids,
                    "attention_mask": mask,
                    "token_type_ids": types,
                }.get(spec.name)
                if src is None:
                    raise RuntimeError(f"Unsupported reranker input {spec.name!r}")
                feed[spec.name] = src.astype(dtype, copy=False)
            logits = np.asarray(self._session.run(None, feed)[0], dtype=np.float32)
            out.extend(logits.reshape(len(chunk), -1)[:, 0].tolist())
        return np.asarray(out, dtype=np.float32)


def load_reranker(model_name: str | None) -> CrossEncoderReranker:
    name = model_name or DEFAULT_RERANKER_MODEL
    with _LOCK:
        hit = _LOADED.get(name)
        if hit is None:
            hit = CrossEncoderReranker(name)
            _LOADED[name] = hit
        return hit


def _protected_ids(query: str, results: Sequence[Dict]) -> List[str]:
    """Ids that should resist CE demotion: identifier hits or full-phrase match."""
    q = query or ""
    q_norm = normalize_phrase(q)
    idents = {m.group(0).lower() for m in _IDENT.finditer(q)}
    q_tokens = [t for t in tokenize(q) if len(t) > 2]
    protected: List[str] = []
    for item in results:
        text = item.get("text") or ""
        text_norm = normalize_phrase(text)
        text_l = text.lower()
        node_id = item["node_id"]
        if q_norm and q_norm in text_norm:
            protected.append(node_id)
            continue
        if idents and any(ident in text_l for ident in idents):
            protected.append(node_id)
            continue
        if q_tokens:
            text_tokens = set(tokenize(text))
            if all(t in text_tokens for t in q_tokens):
                protected.append(node_id)
    return protected


def _order_by_scores(ids: Sequence[str], scores: Sequence[float]) -> List[str]:
    paired = sorted(zip(ids, scores), key=lambda pair: (-float(pair[1]), pair[0]))
    return [node_id for node_id, _ in paired]


def apply_strategy(
    query: str,
    head: List[Dict],
    scores: Sequence[float],
    *,
    strategy: str,
    rrf_k: int = DEFAULT_RRF_K,
    gate_margin: float = DEFAULT_GATE_MARGIN,
) -> List[Dict]:
    """Reorder ``head`` using CE ``scores`` and ``strategy``. Pure function for tests."""
    strategy = normalize_rerank_strategy(strategy)
    ids = [r["node_id"] for r in head]
    by_id = {r["node_id"]: dict(r) for r in head}
    for node_id, score in zip(ids, scores):
        by_id[node_id]["rerank_score"] = round(float(score), 6)

    ce_order = _order_by_scores(ids, scores)

    if strategy == "replace":
        return [by_id[node_id] for node_id in ce_order]

    if strategy == "gated":
        ordered_scores = sorted((float(s) for s in scores), reverse=True)
        use_ce = len(ordered_scores) >= 2 and (
            ordered_scores[0] - ordered_scores[1]
        ) >= float(gate_margin)
        order = ce_order if use_ce else list(ids)
        for node_id in order:
            by_id[node_id]["rerank_gated"] = use_ce
        return [by_id[node_id] for node_id in order]

    lists: List[List[str]] = [ids, ce_order]
    if strategy == "protect":
        protected = _protected_ids(query, head)
        if protected:
            lists.append(protected)

    fused = rrf_fuse(lists, k=rrf_k)
    for node_id, score in fused.items():
        by_id[node_id]["rerank_fuse"] = round(float(score), 6)
    order = sorted(fused, key=lambda node_id: (-fused[node_id], node_id))
    return [by_id[node_id] for node_id in order]


def rerank(
    query: str,
    results: List[Dict],
    *,
    model_name: str | None,
    top_k: int,
    strategy: str | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    gate_margin: float = DEFAULT_GATE_MARGIN,
    scores: Optional[Sequence[float]] = None,
) -> List[Dict]:
    """Reorder the first ``top_k`` results; keep the tail unchanged.

    ``scores`` is optional: pass precomputed CE logits in unit tests to avoid
    loading the ONNX model.
    """
    if not results:
        return results
    head, tail = results[:top_k], results[top_k:]
    if scores is None:
        ce_scores = load_reranker(model_name).score(
            query, [r.get("text") or "" for r in head]
        )
    else:
        if len(scores) != len(head):
            raise ValueError("scores length must match the rerank head")
        ce_scores = scores
    ranked = apply_strategy(
        query,
        head,
        ce_scores,
        strategy=normalize_rerank_strategy(strategy),
        rrf_k=rrf_k,
        gate_margin=gate_margin,
    )
    return ranked + tail
