"""Graph traversal handlers for MCP Graph Memory."""

import logging
import math
import time
from typing import Any, Dict, List, Optional

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.compact_recall import decorate_recall_response
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.mcp_handlers_search import search
from graph_memory_mcp.graph_memory.utils import (
    ensure_text,
    mcp_handler,
    normalize_owner_id,
    require_node_id,
    success_response,
    touch_nodes,
)

logger = logging.getLogger(__name__)


def _load_edges_between_nodes(
    db: FalkorDBClient, node_ids: List[str], owner_id: str
) -> List[Dict]:
    if not node_ids:
        return []

    edges: List[Dict] = []
    for row in db.edges_between(node_ids, owner_id):
        edges.append(
            {
                "from_id": str(row[0]),
                "to_id": str(row[2]),
                "relation_type": ensure_text(row[1]),
                "properties": row[3] if len(row) > 3 else {},
            }
        )
    return edges


def _bfs_expand(
    db: FalkorDBClient,
    *,
    owner_id: str,
    seed_labels: Dict[str, Dict[str, int]],
    depth: int,
    budget: int,
    include_outdated: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Iterative multi-source BFS with a total node budget.

    Expands one hop per query (`O(frontier × avg_degree)` reads, no
    variable-length path explosion on hub nodes); stops as soon as `budget`
    nodes are collected. `seed_labels`: uid -> {seed_id: hop} initial labels;
    labels propagate to neighbors for per-seed hop ranking.
    """
    visited: Dict[str, Dict[str, Any]] = {}
    init_rows = db.bfs_init_rows(list(seed_labels), owner_id)
    for row in init_rows[:budget]:
        uid = str(row[0])
        visited[uid] = {
            "node_id": uid,
            "node_type": row[1],
            "text": ensure_text(row[2]),
            "touched_at": row[3],
            "access_count": row[4],
            "seed_hops": dict(seed_labels.get(uid, {uid: 0})),
        }

    frontier = list(visited)
    for hop in range(1, depth + 1):
        remaining = budget - len(visited)
        if remaining <= 0 or not frontier:
            break
        step_rows = db.bfs_step_rows(
            frontier=frontier,
            seen=list(visited),
            owner_id=owner_id,
            remaining=remaining,
            include_outdated=include_outdated,
        )
        new_frontier: List[str] = []
        for row in step_rows:
            uid = str(row[0])
            if uid in visited:
                continue
            seed_hops: Dict[str, int] = {}
            for parent in row[5] or []:
                for seed_id in visited.get(str(parent), {}).get("seed_hops", {}):
                    seed_hops.setdefault(seed_id, hop)
            visited[uid] = {
                "node_id": uid,
                "node_type": row[1],
                "text": ensure_text(row[2]),
                "touched_at": row[3],
                "access_count": row[4],
                "seed_hops": seed_hops,
            }
            new_frontier.append(uid)
        frontier = new_frontier
    return visited


def _parse_seed_hop_entry(entry: Any) -> tuple[str, int]:
    seed_raw: Any
    hop_raw: Any
    if isinstance(entry, dict):
        seed_raw = entry.get("seed_id", entry.get("sid"))
        hop_raw = entry.get("hop")
    elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
        seed_raw, hop_raw = entry[0], entry[1]
    else:
        raise ValueError(f"Unexpected seed hop entry: {entry!r}")
    if seed_raw is None or hop_raw is None:
        raise ValueError(f"Missing seed_id or hop in entry: {entry!r}")
    try:
        return str(ensure_text(seed_raw)), int(hop_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid seed hop entry: {entry!r}") from exc


def _rank_recall_score(
    seed_hops: Any,
    similarity_by_seed: Dict[str, float],
    hop_decay: float,
) -> tuple[float, int]:
    """Best decayed similarity across seeds and the true minimal hop distance."""
    best_score = 0.0
    min_hop: int | None = None
    for entry in seed_hops or []:
        seed_key, hop = _parse_seed_hop_entry(entry)
        seed_similarity = similarity_by_seed.get(seed_key, 0.0)
        score = seed_similarity * (hop_decay**hop)
        if score > best_score:
            best_score = score
        if min_hop is None or hop < min_hop:
            min_hop = hop
    return best_score, min_hop or 0


def _time_aware_factor(
    config: MCPServerConfig,
    *,
    touched_at_ms: Any,
    access_count: Any,
) -> float:
    """Multiplicative recency/usage boost for recall ranking (1.0 when disabled)."""
    factor = 1.0
    w_rec = max(0.0, min(1.0, getattr(config, "recall_recency_weight", 0.0)))
    if w_rec > 0 and isinstance(touched_at_ms, (int, float)) and touched_at_ms > 0:
        half_life = max(0.1, getattr(config, "recall_recency_half_life_days", 30.0))
        age_days = max(0.0, (time.time() * 1000 - touched_at_ms) / 86_400_000)
        factor *= (1.0 - w_rec) + w_rec * (0.5 ** (age_days / half_life))
    w_use = max(0.0, min(1.0, getattr(config, "recall_usage_weight", 0.0)))
    if w_use > 0:
        count = access_count if isinstance(access_count, (int, float)) else 0
        usage = min(1.0, math.log1p(max(0, count)) / math.log1p(100))
        factor *= (1.0 - w_use) + w_use * usage
    return factor


@mcp_handler
def get_context(
    db: FalkorDBClient,
    config: Any,
    *,
    node_id: str,
    owner_id: str = "default",
    depth: Optional[int] = None,
    max_nodes: Optional[int] = None,
    offset: int = 0,
    include_outdated: bool = False,
) -> Dict:
    """Get subgraph context around a node."""
    owner_id = normalize_owner_id(owner_id)
    node_id = require_node_id(node_id)
    depth = max(
        0, min(depth or config.subgraph_default_depth, config.subgraph_max_depth)
    )
    effective_max_nodes: int = min(
        max_nodes or config.subgraph_default_max_nodes, config.subgraph_max_nodes_limit
    )
    offset = max(0, offset)

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict] = []
    if offset == 0:
        # Iterative BFS with a node budget — no [*0..depth] path explosion.
        visited = _bfs_expand(
            db,
            owner_id=owner_id,
            seed_labels={node_id: {node_id: 0}},
            depth=depth,
            budget=effective_max_nodes,
            include_outdated=include_outdated,
        )
        for uid, record in visited.items():
            nodes[uid] = {
                "node_id": uid,
                "node_type": record["node_type"],
                "text": record["text"],
            }
        paginated = False
    else:
        # Paginated (operator/explorer) path: full expansion with stable order.
        for row in db.context_page_rows(
            depth=depth,
            offset=offset,
            limit=effective_max_nodes,
            include_outdated=include_outdated,
            node_id=node_id,
            owner_id=owner_id,
        ):
            current_id = str(row[0])
            nodes[current_id] = {
                "node_id": current_id,
                "node_type": row[1],
                "text": ensure_text(row[2]),
            }
        paginated = True

    if nodes:
        edges = _load_edges_between_nodes(db, list(nodes), owner_id)

    response = success_response(
        nodes=list(nodes.values()),
        edges=edges,
        depth=depth,
        max_nodes=effective_max_nodes,
    )
    if paginated:
        node_count = len(response["nodes"])
        response["offset"] = offset
        response["has_more"] = node_count >= effective_max_nodes
    return response


@mcp_handler
def get_trace(
    db: FalkorDBClient,
    *,
    from_id: str,
    to_id: str,
    owner_id: str = "default",
    max_depth: int = 5,
    directed: bool = True,
) -> Dict:
    """Get shortest path between two nodes (directed by default)."""
    owner_id = normalize_owner_id(owner_id)
    from_id = require_node_id(from_id, "from_id")
    to_id = require_node_id(to_id, "to_id")

    rows = db.shortest_path_row(
        directed=directed,
        max_depth=max_depth,
        from_id=from_id,
        to_id=to_id,
        owner_id=owner_id,
    )
    if not rows:
        return success_response(nodes=[], relations=[], message="No path found")

    row = rows[0]
    nodes = row[0] if len(row) > 0 and row[0] else []
    relations = row[1] if len(row) > 1 and row[1] else []
    if not nodes:
        return success_response(nodes=[], relations=[], message="No path found")
    return success_response(nodes=nodes, relations=relations)


@mcp_handler
def recall_context(
    db: FalkorDBClient,
    config: MCPServerConfig,
    *,
    query: str,
    owner_id: str = "default",
    depth: Optional[int] = None,
    limit: Optional[int] = None,
    max_nodes: Optional[int] = None,
    similarity_threshold: Optional[float] = None,
    include_outdated: bool = False,
    search_type: Optional[str] = None,
    include_paths: bool = False,
    metadata_filter: Optional[Dict] = None,
    compact: bool = False,
) -> Dict:
    """Hybrid semantic search + graph expansion for agent recall."""
    owner_id = normalize_owner_id(owner_id)
    depth = max(
        0,
        min(
            depth or config.recall_context_default_depth,
            config.subgraph_max_depth,
        ),
    )
    seed_limit = max(
        1,
        min(
            limit or config.recall_context_default_seed_limit,
            config.max_search_limit,
        ),
    )
    effective_max_nodes = min(
        max_nodes or config.subgraph_default_max_nodes,
        config.subgraph_max_nodes_limit,
    )
    hop_decay = config.recall_context_hop_decay

    search_result = search(
        db,
        config,
        query=query,
        owner_id=owner_id,
        limit=seed_limit,
        similarity_threshold=similarity_threshold,
        include_outdated=include_outdated,
        search_type=search_type,
        metadata_filter=metadata_filter,
        compact=False,
    )
    if not search_result.get("success"):
        return search_result

    # Drop search envelope fields; recall builds its own guidance.
    seeds = list(search_result.get("results") or [])
    if not seeds:
        empty = success_response(
            query=query,
            seeds=[],
            nodes=[],
            edges=[],
            paths=[],
            depth=depth,
            max_nodes=effective_max_nodes,
            seed_limit=seed_limit,
        )
        return decorate_recall_response(
            empty,
            compact=compact,
            snippet_chars=config.compact_snippet_chars,
            token_budget=config.compact_recall_token_budget,
            owner_id=owner_id,
        )

    similarity_by_seed = {
        str(seed["node_id"]): float(seed.get("similarity", 0.0)) for seed in seeds
    }

    # Iterative multi-source BFS with a node budget — replaces the former
    # [*0..depth] expansion that exploded on hub nodes.
    visited = _bfs_expand(
        db,
        owner_id=owner_id,
        seed_labels={str(s["node_id"]): {str(s["node_id"]): 0} for s in seeds},
        depth=depth,
        budget=effective_max_nodes,
        include_outdated=include_outdated,
    )

    expanded: List[Dict] = []
    for record in visited.values():
        seed_hops = [
            {"seed_id": sid, "hop": hop} for sid, hop in record["seed_hops"].items()
        ]
        score, min_hop = _rank_recall_score(seed_hops, similarity_by_seed, hop_decay)
        score *= _time_aware_factor(
            config,
            touched_at_ms=record["touched_at"],
            access_count=record["access_count"],
        )
        expanded.append(
            {
                "node_id": record["node_id"],
                "node_type": record["node_type"],
                "text": record["text"],
                "score": round(score, 6),
                "min_hop": min_hop,
            }
        )

    expanded.sort(
        key=lambda node: (-node["score"], node["node_id"]),
    )
    ranked_nodes = expanded[:effective_max_nodes]
    node_ids = [node["node_id"] for node in ranked_nodes]
    edges = _load_edges_between_nodes(db, node_ids, owner_id)

    paths: List[Dict] = []
    if include_paths and len(seeds) >= 2:
        top_from = seeds[0]["node_id"]
        top_to = seeds[1]["node_id"]
        # Undirected: consistent with the undirected BFS expansion above.
        trace = get_trace(
            db,
            from_id=top_from,
            to_id=top_to,
            owner_id=owner_id,
            max_depth=max(depth, 5),
            directed=False,
        )
        if trace.get("success") and trace.get("nodes"):
            paths.append(
                {
                    "from_id": top_from,
                    "to_id": top_to,
                    "nodes": trace.get("nodes", []),
                    "relations": trace.get("relations", []),
                }
            )

    touch_nodes(db, node_ids, owner_id)

    return decorate_recall_response(
        success_response(
            query=query,
            seeds=seeds,
            nodes=ranked_nodes,
            edges=edges,
            paths=paths,
            depth=depth,
            max_nodes=effective_max_nodes,
            seed_limit=seed_limit,
        ),
        compact=compact,
        snippet_chars=config.compact_snippet_chars,
        token_budget=config.compact_recall_token_budget,
        owner_id=owner_id,
    )
