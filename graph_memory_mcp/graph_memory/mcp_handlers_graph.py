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
    depth = min(depth or config.subgraph_default_depth, config.subgraph_max_depth)
    max_nodes = min(
        max_nodes or config.subgraph_default_max_nodes, config.subgraph_max_nodes_limit
    )

    query = f"""
    MATCH path = (center)-[*0..{depth}]-(connected)
    WHERE id(center) = $node_id
      AND center.owner_id = $owner_id
      AND connected.owner_id = $owner_id
    WITH collect(DISTINCT connected) as nodes
    LIMIT {max_nodes}
    MATCH (n)-[r]->(m)
    WHERE n IN nodes AND m IN nodes
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

    result = execute_query(db, query, {"node_id": int(node_id), "owner_id": owner_id})

    nodes = {}
    edges = []

    if result and hasattr(result, "result_set"):
        for row in result.result_set:
            from_id = str(row[0])
            to_id = str(row[4])

            if from_id not in nodes:
                nodes[from_id] = {
                    "node_id": from_id,
                    "node_type": row[1],
                    "text": ensure_text(row[2]),
                }

            if to_id not in nodes:
                nodes[to_id] = {
                    "node_id": to_id,
                    "node_type": row[5],
                    "text": ensure_text(row[6]),
                }

            edges.append(
                {
                    "from_id": from_id,
                    "to_id": to_id,
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
