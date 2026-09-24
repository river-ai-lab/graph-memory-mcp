"""Compact recall envelopes: snippets, token budget, suggested_next."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


def estimate_tokens(text: Optional[str]) -> int:
    """Rough token estimate (~4 chars/token). Enough for budgets, not billing."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def snippet_text(text: Optional[str], max_chars: int) -> str:
    """Truncate to max_chars on a word boundary when possible."""
    if not text:
        return ""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    cut = text[: max_chars + 1]
    space = cut.rfind(" ")
    if space >= max(24, max_chars // 3):
        cut = cut[:space]
    else:
        cut = text[:max_chars]
    return cut.rstrip() + "…"


def _fmt_metadata_filter(metadata_filter: Optional[Dict]) -> str:
    if not metadata_filter:
        return ""
    return f", metadata_filter={metadata_filter!r}"


def suggested_next_for_search(
    *,
    results: List[Dict],
    query: str,
    owner_id: str,
    metadata_filter: Optional[Dict] = None,
    compact: bool = False,
    truncated: bool = False,
) -> List[str]:
    """Next tool calls an agent should prefer after search."""
    mf = _fmt_metadata_filter(metadata_filter)
    if not results:
        return [
            f'get_brief(owner_id="{owner_id}")',
            f'search(query="{query}", owner_id="{owner_id}", similarity_threshold=0.4{mf})',
        ]

    top = results[:3]
    suggestions: List[str] = []
    best = top[0]
    suggestions.append(
        f'get_context(node_id="{best["node_id"]}", owner_id="{owner_id}", depth=1)'
    )
    if compact or truncated:
        for hit in top[:2]:
            suggestions.append(
                f'get_node(node_id="{hit["node_id"]}", owner_id="{owner_id}")'
            )
    elif len(top) >= 2:
        suggestions.append(
            f'get_context(node_id="{top[1]["node_id"]}", owner_id="{owner_id}", depth=1)'
        )
    return suggestions


def suggested_next_for_recall(
    *,
    seeds: List[Dict],
    nodes: List[Dict],
    owner_id: str,
    compact: bool = False,
    truncated: bool = False,
) -> List[str]:
    """Next tool calls after recall_context."""
    ids: List[str] = []
    for item in seeds[:2]:
        nid = str(item.get("node_id", ""))
        if nid and nid not in ids:
            ids.append(nid)
    for item in nodes[:3]:
        nid = str(item.get("node_id", ""))
        if nid and nid not in ids:
            ids.append(nid)

    if not ids:
        return [f'get_brief(owner_id="{owner_id}")']

    suggestions = [
        f'get_context(node_id="{ids[0]}", owner_id="{owner_id}", depth=1)',
    ]
    if (compact or truncated) and ids:
        suggestions.append(f'get_node(node_id="{ids[0]}", owner_id="{owner_id}")')
    if len(ids) >= 2:
        suggestions.append(
            f'get_trace(from_id="{ids[0]}", to_id="{ids[1]}", owner_id="{owner_id}")'
        )
    return suggestions


def _compact_node_list(
    nodes: List[Dict],
    *,
    text_key: str,
    snippet_chars: int,
    token_budget: int,
) -> tuple[List[Dict], int, bool]:
    """Return compacted nodes, tokens used, truncated flag."""
    out: List[Dict] = []
    used = 0
    truncated = False
    for node in nodes:
        item = dict(node)
        full = item.get(text_key) or item.get("text") or ""
        full_s = str(full) if full is not None else ""
        cost = estimate_tokens(full_s)
        if used + cost > token_budget and out:
            truncated = True
            break
        if len(full_s) > snippet_chars or cost > token_budget - used:
            item["snippet"] = snippet_text(full_s, snippet_chars)
            item.pop("text", None)
            truncated = truncated or len(full_s) > snippet_chars
            used += estimate_tokens(item["snippet"])
        else:
            used += cost
        out.append(item)
    if len(out) < len(nodes):
        truncated = True
    return out, used, truncated


def decorate_search_response(
    response: Dict[str, Any],
    *,
    compact: bool,
    snippet_chars: int,
    token_budget: int,
    query: str,
    owner_id: str,
    metadata_filter: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Copy + attach guidance; optionally compact result texts under a budget."""
    if not response.get("success"):
        return response

    out = copy.deepcopy(response)
    results: List[Dict] = list(out.get("results") or [])
    tokens_used = sum(estimate_tokens(r.get("text")) for r in results)
    truncated = False

    if compact:
        results, tokens_used, truncated = _compact_node_list(
            results,
            text_key="text",
            snippet_chars=snippet_chars,
            token_budget=token_budget,
        )
        out["results"] = results
        out["facts"] = [n for n in results if n.get("node_type") == "Fact"]
        out["entities"] = [n for n in results if n.get("node_type") == "Entity"]

    out["compact"] = compact
    out["budget"] = {
        "tokens_est": tokens_used,
        "tokens_max": token_budget if compact else None,
        "truncated": truncated,
        "mode": "compact" if compact else "full",
    }
    out["suggested_next"] = suggested_next_for_search(
        results=results,
        query=query,
        owner_id=owner_id,
        metadata_filter=metadata_filter,
        compact=compact,
        truncated=truncated,
    )
    out["do_not"] = (
        "Do not broaden the same search; pick 1-3 node_ids and expand "
        "with get_context / get_node."
        if results
        else "Do not invent facts; lower similarity_threshold or check get_brief."
    )
    return out


def decorate_recall_response(
    response: Dict[str, Any],
    *,
    compact: bool,
    snippet_chars: int,
    token_budget: int,
    owner_id: str,
) -> Dict[str, Any]:
    """Copy + attach guidance; optionally compact seed/node texts."""
    if not response.get("success"):
        return response

    out = copy.deepcopy(response)
    seeds: List[Dict] = list(out.get("seeds") or [])
    nodes: List[Dict] = list(out.get("nodes") or [])
    tokens_used = sum(estimate_tokens(s.get("text")) for s in seeds) + sum(
        estimate_tokens(n.get("text")) for n in nodes
    )
    truncated = False

    if compact:
        # Prefer keeping seeds; spend remaining budget on expanded nodes.
        seeds, seed_tokens, seed_trunc = _compact_node_list(
            seeds,
            text_key="text",
            snippet_chars=snippet_chars,
            token_budget=max(snippet_chars // 4, token_budget // 3),
        )
        remaining = max(0, token_budget - seed_tokens)
        nodes, node_tokens, node_trunc = _compact_node_list(
            nodes,
            text_key="text",
            snippet_chars=snippet_chars,
            token_budget=remaining,
        )
        out["seeds"] = seeds
        out["nodes"] = nodes
        tokens_used = seed_tokens + node_tokens
        truncated = seed_trunc or node_trunc

    out["compact"] = compact
    out["budget"] = {
        "tokens_est": tokens_used,
        "tokens_max": token_budget if compact else None,
        "truncated": truncated,
        "mode": "compact" if compact else "full",
    }
    out["suggested_next"] = suggested_next_for_recall(
        seeds=seeds,
        nodes=nodes,
        owner_id=owner_id,
        compact=compact,
        truncated=truncated,
    )
    out["do_not"] = (
        "Treat returned text/snippets as already read; expand only 1-3 ids. "
        "If truncated, do not repeat a broader recall_context."
    )
    return out
