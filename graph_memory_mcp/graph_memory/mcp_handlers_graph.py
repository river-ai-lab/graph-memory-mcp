"""Graph traversal handlers for MCP Graph Memory."""

import logging
from typing import Any, Dict, Optional

from graph_memory_mcp.graph_memory.database import FalkorDBClient
from graph_memory_mcp.graph_memory.utils import (
    ensure_text,
    execute_query,
    mcp_handler,
    normalize_owner_id,
    success_response,
)

logger = logging.getLogger(__name__)


@mcp_handler
def get_context(
    db: FalkorDBClient,
    config: Any,
    *,
    node_id: str,
    owner_id: str = "default",
    depth: Optional[int] = None,
    max_nodes: Optional[int] = None,
) -> Dict:
    """Get subgraph context around a node."""
    owner_id = normalize_owner_id(owner_id)
    depth = max(
        0, min(depth or config.subgraph_default_depth, config.subgraph_max_depth)
    )
    max_nodes = min(
        max_nodes or config.subgraph_default_max_nodes, config.subgraph_max_nodes_limit
    )

    nodes_query = f"""
    MATCH path = (center)-[*0..{depth}]-(connected)
    WHERE id(center) = $node_id
      AND center.owner_id = $owner_id
      AND connected.owner_id = $owner_id
    WITH DISTINCT connected
    LIMIT {max_nodes}
    RETURN
        id(connected) as node_id,
        labels(connected)[0] as node_type,
        connected.text as text
    """

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
        edges_query = """
        MATCH (n)-[r]->(m)
        WHERE id(n) IN $node_ids AND id(m) IN $node_ids
        RETURN DISTINCT
            id(n) as from_id,
            labels(n)[0] as from_type,
            n.text as from_text,
            type(r) as relation_type,
            id(m) as to_id,
            labels(m)[0] as to_type,
            m.text as to_text,
            properties(r) as relation_props
        """

        edges_result = execute_query(
            db,
            edges_query,
            {"node_ids": [int(current_id) for current_id in nodes]},
        )
        if edges_result and hasattr(edges_result, "result_set"):
            for row in edges_result.result_set:
                edges.append(
                    {
                        "from_id": str(row[0]),
                        "to_id": str(row[4]),
                        "relation_type": ensure_text(row[3]),
                        "properties": row[7] if len(row) > 7 else {},
                    }
                )

    return success_response(
        nodes=list(nodes.values()),
        edges=edges,
        depth=depth,
        max_nodes=max_nodes,
    )


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
        return success_response(path=None, message="No path found")

    row = result.result_set[0]
    return success_response(nodes=row[0], relations=row[1])
