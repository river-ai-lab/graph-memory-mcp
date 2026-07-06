"""Graph traversal handlers for MCP Graph Memory."""

import logging
from typing import Any, Dict, List, Optional

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.mcp_handlers_search import search
from graph_memory_mcp.graph_memory.utils import (
    ensure_text,
    execute_query,
    mcp_handler,
    normalize_owner_id,
    success_response,
)

logger = logging.getLogger(__name__)


def _load_edges_between_nodes(db: FalkorDBClient, node_ids: List[str]) -> List[Dict]:
    if not node_ids:
        return []

    edges_query = """
    MATCH (n)-[r]->(m)
    WHERE id(n) IN $node_ids AND id(m) IN $node_ids
    RETURN DISTINCT
        id(n) as from_id,
        type(r) as relation_type,
        id(m) as to_id,
        properties(r) as relation_props
    """
    edges: List[Dict] = []
    edges_result = execute_query(
        db,
        edges_query,
        {"node_ids": [int(node_id) for node_id in node_ids]},
    )
    if edges_result and hasattr(edges_result, "result_set"):
        for row in edges_result.result_set:
            edges.append(
                {
                    "from_id": str(row[0]),
                    "to_id": str(row[2]),
                    "relation_type": ensure_text(row[1]),
                    "properties": row[3] if len(row) > 3 else {},
                }
            )
    return edges


def _parse_seed_hop_entry(entry: Any) -> tuple[int, int]:
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
        return int(seed_raw), int(hop_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid seed hop entry: {entry!r}") from exc


def _rank_recall_score(
    seed_hops: Any,
    similarity_by_seed: Dict[str, float],
    hop_decay: float,
) -> tuple[float, int]:
    best_score = 0.0
    min_hop = 0
    for entry in seed_hops or []:
        seed_id, hop = _parse_seed_hop_entry(entry)
        seed_key = str(seed_id)
        seed_similarity = similarity_by_seed.get(seed_key, 0.0)
        score = seed_similarity * (hop_decay**hop)
        if score > best_score:
            best_score = score
            min_hop = hop
    return best_score, min_hop


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
) -> Dict:
    """Get subgraph context around a node."""
    owner_id = normalize_owner_id(owner_id)
    depth = max(
        0, min(depth or config.subgraph_default_depth, config.subgraph_max_depth)
    )
    effective_max_nodes: int = min(
        max_nodes or config.subgraph_default_max_nodes, config.subgraph_max_nodes_limit
    )
    offset = max(0, offset)

    if offset == 0:
        nodes_query = f"""
    MATCH path = (center)-[*0..{depth}]-(connected)
    WHERE id(center) = $node_id
      AND center.owner_id = $owner_id
      AND connected.owner_id = $owner_id
    WITH DISTINCT connected
    LIMIT {effective_max_nodes}
    RETURN
        id(connected) as node_id,
        labels(connected)[0] as node_type,
        connected.text as text
    """
        paginated = False
    else:
        nodes_query = f"""
    MATCH path = (center)-[*0..{depth}]-(connected)
    WHERE id(center) = $node_id
      AND center.owner_id = $owner_id
      AND connected.owner_id = $owner_id
    WITH DISTINCT connected
    ORDER BY id(connected)
    SKIP {offset}
    LIMIT {effective_max_nodes}
    RETURN
        id(connected) as node_id,
        labels(connected)[0] as node_type,
        connected.text as text
    """
        paginated = True

    nodes = {}
    edges = []

    nodes_result = execute_query(
        db,
        nodes_query,
        {"node_id": int(node_id), "owner_id": owner_id},
    )
    if nodes_result and hasattr(nodes_result, "result_set"):
        for row in nodes_result.result_set:
            current_id = str(row[0])
            nodes[current_id] = {
                "node_id": current_id,
                "node_type": row[1],
                "text": ensure_text(row[2]),
            }

    if nodes:
        edges = _load_edges_between_nodes(db, list(nodes))

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
) -> Dict:
    """Get shortest path between two nodes."""
    owner_id = normalize_owner_id(owner_id)

    query = f"""
    MATCH (a), (b)
    WHERE id(a) = $from_id AND id(b) = $to_id
      AND a.owner_id = $owner_id AND b.owner_id = $owner_id
    WITH shortestPath((a)-[*..{max_depth}]->(b)) as path
    RETURN [n in nodes(path) | {{
        node_id: toString(id(n)),
        node_type: labels(n)[0],
        text: n.text
    }}] as nodes,
    [r in relationships(path) | {{
        relation_type: type(r)
    }}] as relations
    """

    result = execute_query(
        db,
        query,
        {
            "from_id": int(from_id),
            "to_id": int(to_id),
            "owner_id": owner_id,
        },
    )

    if not result:
        return success_response(nodes=[], relations=[], message="No path found")

    row = result.result_set[0]
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
    include_paths: bool = True,
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
    seed_limit = limit or config.recall_context_default_seed_limit
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
    )
    if not search_result.get("success"):
        return search_result

    seeds = search_result.get("results", [])
    if not seeds:
        return success_response(
            query=query,
            seeds=[],
            nodes=[],
            edges=[],
            paths=[],
            depth=depth,
            max_nodes=effective_max_nodes,
            seed_limit=seed_limit,
        )

    similarity_by_seed = {
        str(seed["node_id"]): float(seed.get("similarity", 0.0)) for seed in seeds
    }
    seed_ids = [int(seed["node_id"]) for seed in seeds]

    expand_query = f"""
    UNWIND $seed_ids AS sid
    MATCH (seed)
    WHERE id(seed) = sid AND seed.owner_id = $owner_id
    MATCH path = (seed)-[*0..{depth}]-(connected)
    WHERE connected.owner_id = $owner_id
    WITH connected, sid, min(length(path)) AS hop
    WITH connected, collect({{seed_id: sid, hop: hop}}) AS seed_hops
    RETURN
        id(connected) AS node_id,
        labels(connected)[0] AS node_type,
        connected.text AS text,
        seed_hops
    """

    expanded: List[Dict] = []
    expand_result = execute_query(
        db,
        expand_query,
        {"seed_ids": seed_ids, "owner_id": owner_id},
    )
    if expand_result and hasattr(expand_result, "result_set"):
        for row in expand_result.result_set:
            score, min_hop = _rank_recall_score(row[3], similarity_by_seed, hop_decay)
            expanded.append(
                {
                    "node_id": str(row[0]),
                    "node_type": row[1],
                    "text": ensure_text(row[2]),
                    "score": round(score, 6),
                    "min_hop": min_hop,
                }
            )

    expanded.sort(
        key=lambda node: (-node["score"], node["node_id"]),
    )
    ranked_nodes = expanded[:effective_max_nodes]
    node_ids = [node["node_id"] for node in ranked_nodes]
    edges = _load_edges_between_nodes(db, node_ids)

    paths: List[Dict] = []
    if include_paths and len(seeds) >= 2:
        top_from = seeds[0]["node_id"]
        top_to = seeds[1]["node_id"]
        trace = get_trace(
            db,
            from_id=top_from,
            to_id=top_to,
            owner_id=owner_id,
            max_depth=max(depth, 5),
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

    return success_response(
        query=query,
        seeds=seeds,
        nodes=ranked_nodes,
        edges=edges,
        paths=paths,
        depth=depth,
        max_nodes=effective_max_nodes,
        seed_limit=seed_limit,
    )
