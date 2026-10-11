"""Hybrid search rank: cosine + identifier match + recency.

Lexical boost only fires on distinctive tokens (job/RUN ids, symbols, S3
paths, sizes like 48Gi). Bare years are not tokens — they made old facts
outrank a newer one that actually names the identifier.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

_S3 = re.compile(r"s3://\S+", re.IGNORECASE)
_RUN = re.compile(r"\b(?:RUN[_ ]?)?\d{8}T\d{6}Z\b", re.IGNORECASE)
_SYMBOL = re.compile(r"\b_?[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b")
_SIZE = re.compile(r"\b\d+(?:Gi|Mi|Ti|cpu)\b", re.IGNORECASE)
_EPOCH = re.compile(r"\bepoch\s+\d+\b", re.IGNORECASE)
_MIXED = re.compile(r"\b(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{4,}\b")


def hard_tokens(query: str) -> List[str]:
    """Distinctive identifiers in a query, de-duplicated, original case kept."""
    if not query:
        return []
    found: List[str] = []
    seen = set()
    for pattern in (_S3, _RUN, _SYMBOL, _SIZE, _EPOCH, _MIXED):
        for match in pattern.findall(query):
            key = match.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(match)
    return found


def lexical_fraction(text: Optional[str], tokens: List[str]) -> float:
    """Share of hard tokens that occur in text (case-insensitive)."""
    if not tokens:
        return 0.0
    hay = (text or "").lower()
    hits = sum(1 for token in tokens if token.lower() in hay)
    return hits / len(tokens)


def recency_factor(
    created_at: Optional[int], now_ms: int, half_life_days: float
) -> float:
    """1.0 at now, halves every half_life_days. Missing timestamp → 0."""
    if created_at is None or half_life_days <= 0:
        return 0.0
    age_days = max(0.0, (now_ms - int(created_at)) / 86_400_000)
    return 0.5 ** (age_days / half_life_days)


def hybrid_score(
    *,
    similarity: float,
    lexical: float,
    recency: float,
    lexical_weight: float,
    recency_weight: float,
    has_hard_tokens: bool,
) -> float:
    """Blend cosine with lexical and recency. Weights are clamped into [0, 1]."""
    lex_w = max(0.0, lexical_weight) if has_hard_tokens else 0.0
    rec_w = max(0.0, recency_weight)
    if lex_w + rec_w > 1.0:
        scale = 1.0 / (lex_w + rec_w)
        lex_w *= scale
        rec_w *= scale
    semantic_w = 1.0 - lex_w - rec_w
    return semantic_w * similarity + lex_w * lexical + rec_w * recency


def rerank_results(
    results: List[Dict],
    *,
    query: str,
    now_ms: int,
    lexical_weight: float,
    recency_weight: float,
    half_life_days: float,
) -> List[Dict]:
    """Return a new list sorted by hybrid score. `similarity` is left intact."""
    tokens = hard_tokens(query)
    ranked: List[Dict] = []
    for item in results:
        lexical = lexical_fraction(item.get("text"), tokens)
        recency = recency_factor(item.get("created_at"), now_ms, half_life_days)
        score = hybrid_score(
            similarity=float(item.get("similarity") or 0.0),
            lexical=lexical,
            recency=recency,
            lexical_weight=lexical_weight,
            recency_weight=recency_weight,
            has_hard_tokens=bool(tokens),
        )
        updated = dict(item)
        updated["lexical"] = round(lexical, 4)
        updated["recency"] = round(recency, 4)
        updated["score"] = round(score, 6)
        ranked.append(updated)
    ranked.sort(
        key=lambda row: (
            -row["score"],
            -row.get("similarity", 0),
            row.get("node_id", ""),
        )
    )
    return ranked
