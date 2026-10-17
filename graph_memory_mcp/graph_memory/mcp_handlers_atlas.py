"""Atlas handlers: Collections, Users, Projects, and access control.

Extended server only. Requires ArcadeDB backend with shared_graph=true.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from graph_memory_mcp.graph_memory.utils import new_uid

logger = logging.getLogger(__name__)


def check_node_access(
    db: Any,
    node_id: str,
    owner_id: str,
    viewer_id: str,
    require_write: bool = False,
) -> tuple[bool, Optional[str]]:
    """Check if viewer can access a node (read or write).
    
    Args:
        db: Database client
        node_id: Node to check
        owner_id: Owner scope
        viewer_id: Viewer requesting access
        require_write: If True, require owner access
        
    Returns:
        (has_access, error_message) tuple
    """
    if not db.shared_graph:
        # No ACL in per-owner mode
        return True, None
    
    from graph_memory_mcp.graph_memory.backends.arcade_ops import expand_principal_tokens
    
    viewer_tokens = expand_principal_tokens(db, viewer_id, owner_id)
    
    # Write access requires owner
    if require_write and f"owner:{owner_id}" not in viewer_tokens:
        return False, "Write access requires owner permission"
    
    # Read access: check if node acl_tokens intersect viewer_tokens
    with db.owner_scope(owner_id):
        for label in ("Fact", "Entity", "Collection", "User", "Project"):
            rows = db.query(
                f"SELECT acl_tokens FROM {label} WHERE uid = :uid AND owner_id = :owner LIMIT 1",
                {"uid": node_id, "owner": owner_id},
            )
            if rows:
                node_tokens = rows[0].get("acl_tokens") or []
                # Check intersection
                if "ALL" in node_tokens or any(t in viewer_tokens for t in node_tokens):
                    return True, None
                return False, "Access denied: node not visible to viewer"
    
    return False, "Node not found"


def ensure_default_collection(db: Any, owner_id: str, user_id: str) -> str:
    """Ensure user has exactly one default collection; return its uid.
    
    Default collection invariant: every user has one default collection,
    auto-created on first node write without collection_id. Nodes created
    without collection_id go here.
    
    Returns:
        Collection uid
    """
    # Check if user node exists
    user_node = _find_user_node(db, user_id, owner_id)
    if not user_node:
        user_node = _create_user_node(db, user_id, owner_id)
    
    # Check if user already has a default collection
    default_coll = _find_default_collection(db, user_id, owner_id)
    if default_coll:
        return default_coll["node_id"]
    
    # Create default collection
    coll_uid = new_uid()
    now_ms = int(__import__("time").time() * 1000)
    
    # Collection node
    with db.owner_scope(owner_id):
        fields = {
            "uid": coll_uid,
            "owner_id": owner_id,
            "text": f"Default collection for {user_id}",
            "description": f"Auto-created default collection for user {user_id}",
            "status": "active",
            "created_at": now_ms,
            "updated_at": now_ms,
            "metadata_str": '{"is_default": true}',
        }
        # ACL tokens: owner + this user
        if db.shared_graph:
            from graph_memory_mcp.graph_memory.backends.arcade_ops import compute_acl_tokens
            fields["acl_tokens"] = compute_acl_tokens(
                owner_id=owner_id,
                shared_with_ids=[f"user:{user_id}"],
            )
        db._insert("Collection", fields)
    
    # Link user -> collection with HAS_ACCESS
    db.ensure_edge_type("HAS_ACCESS")
    with db.owner_scope(owner_id):
        user_rec = db.query(
            f"SELECT FROM User WHERE uid = :uid AND owner_id = :owner LIMIT 1",
            {"uid": user_node["node_id"], "owner": owner_id},
        )
        coll_rec = db.query(
            f"SELECT FROM Collection WHERE uid = :uid AND owner_id = :owner LIMIT 1",
            {"uid": coll_uid, "owner": owner_id},
        )
        if user_rec and coll_rec:
            from graph_memory_mcp.graph_memory.backends.arcade_ops import _rid
            user_rid = _rid(user_rec[0].get("@rid"))
            coll_rid = _rid(coll_rec[0].get("@rid"))
            db.command(
                f"CREATE EDGE HAS_ACCESS FROM {user_rid} TO {coll_rid} SET created_at = {now_ms}"
            )
    
    logger.info("Created default collection %s for user %s", coll_uid, user_id)
    return coll_uid


def _find_user_node(db: Any, user_id: str, owner_id: str) -> Optional[Dict]:
    """Find User node by user_id."""
    with db.owner_scope(owner_id):
        rows = db.query(
            "SELECT uid, text FROM User WHERE owner_id = :owner AND text = :user_id LIMIT 1",
            {"owner": owner_id, "user_id": user_id},
        )
        if rows:
            return {"node_id": rows[0].get("uid"), "text": rows[0].get("text")}
    return None


def _create_user_node(db: Any, user_id: str, owner_id: str) -> Dict:
    """Create User node."""
    uid = new_uid()
    now_ms = int(__import__("time").time() * 1000)
    with db.owner_scope(owner_id):
        fields = {
            "uid": uid,
            "owner_id": owner_id,
            "text": user_id,
            "status": "active",
            "created_at": now_ms,
            "updated_at": now_ms,
        }
        if db.shared_graph:
            from graph_memory_mcp.graph_memory.backends.arcade_ops import compute_acl_tokens
            fields["acl_tokens"] = compute_acl_tokens(
                owner_id=owner_id,
                shared_with_ids=[f"user:{user_id}"],
            )
        db._insert("User", fields)
    logger.info("Created User node %s", uid)
    return {"node_id": uid, "text": user_id}


def _find_default_collection(db: Any, user_id: str, owner_id: str) -> Optional[Dict]:
    """Find user's default collection."""
    with db.owner_scope(owner_id):
        # Find collection with metadata.is_default = true
        rows = db.query(
            """SELECT uid, text FROM Collection 
               WHERE owner_id = :owner 
               AND metadata_str LIKE '%is_default": true%'
               AND text LIKE :pattern
               LIMIT 1""",
            {"owner": owner_id, "pattern": f"%{user_id}%"},
        )
        if rows:
            return {"node_id": rows[0].get("uid"), "text": rows[0].get("text")}
    return None


def add_to_collection(
    db: Any,
    node_id: str,
    collection_id: str,
    owner_id: str,
) -> Dict:
    """Add a node to a collection (CONTAINS edge).
    
    Also updates node's acl_tokens to include collection's tokens (propagation).
    
    Returns:
        Success dict with edge info
    """
    try:
        # Create CONTAINS edge
        rows = db.add_to_collection(node_id, collection_id, owner_id)
        
        # Propagate collection's ACL tokens to the node
        if db.shared_graph:
            with db.owner_scope(owner_id):
                # Get collection's acl_tokens
                coll_rec = db.query(
                    "SELECT acl_tokens FROM Collection WHERE uid = :uid AND owner_id = :owner LIMIT 1",
                    {"uid": collection_id, "owner": owner_id},
                )
                
                if coll_rec:
                    coll_tokens = coll_rec[0].get("acl_tokens") or []
                    
                    # Get node's current acl_tokens
                    from graph_memory_mcp.graph_memory.backends.arcade_ops import _rid
                    
                    for label in ("Fact", "Entity", "Collection", "Project"):
                        node_rec = db.query(
                            f"SELECT acl_tokens FROM {label} WHERE uid = :uid AND owner_id = :owner LIMIT 1",
                            {"uid": node_id, "owner": owner_id},
                        )
                        if node_rec:
                            node_tokens = node_rec[0].get("acl_tokens") or []
                            # Merge tokens: node's tokens + collection's tokens + coll:<collection_id>
                            new_tokens = sorted(set(node_tokens + coll_tokens + [f"coll:{collection_id}"]))
                            
                            # Update node
                            db.command(
                                f"UPDATE {label} SET acl_tokens = :tokens WHERE uid = :uid AND owner_id = :owner",
                                {"tokens": new_tokens, "uid": node_id, "owner": owner_id},
                            )
                            break
        
        return {
            "success": True,
            "node_id": node_id,
            "collection_id": collection_id,
            "relation_created": bool(rows),
        }
    except Exception as exc:
        logger.error("Failed to add node %s to collection %s: %s", node_id, collection_id, exc)
        return {
            "success": False,
            "error": str(exc),
            "code": "memory_service_error",
        }


def remove_from_collection(
    db: Any,
    node_id: str,
    collection_id: str,
    owner_id: str,
) -> Dict:
    """Remove a node from a collection (delete CONTAINS edge).
    
    Also removes collection's tokens from node's acl_tokens (revocation).
    
    Returns:
        Success dict
    """
    try:
        with db.owner_scope(owner_id):
            from graph_memory_mcp.graph_memory.backends.arcade_ops import _rid
            
            # Find node
            node_rec = None
            node_label = None
            for label in ("Fact", "Entity", "Collection", "Project"):
                rows = db.query(
                    f"SELECT FROM {label} WHERE uid = :uid AND owner_id = :owner LIMIT 1",
                    {"uid": node_id, "owner": owner_id},
                )
                if rows:
                    node_rec = rows[0]
                    node_label = label
                    break
            
            coll_rec = db.query(
                f"SELECT FROM Collection WHERE uid = :uid AND owner_id = :owner LIMIT 1",
                {"uid": collection_id, "owner": owner_id},
            )
            
            if not node_rec or not coll_rec:
                return {
                    "success": False,
                    "error": "Node or collection not found",
                    "code": "memory_not_found",
                }
            
            node_rid = _rid(node_rec.get("@rid"))
            coll_rid = _rid(coll_rec.get("@rid"))
            
            # Delete CONTAINS edge from collection to node
            result = db.command(
                f"DELETE FROM CONTAINS WHERE @out = {coll_rid} AND @in = {node_rid}"
            )
            
            # Remove collection's tokens from node (revocation)
            if db.shared_graph:
                coll_tokens = coll_rec.get("acl_tokens") or []
                node_tokens = node_rec.get("acl_tokens") or []
                
                # Remove coll:<collection_id> and any tokens that came from the collection
                tokens_to_remove = set([f"coll:{collection_id}"])
                # Don't remove owner/user tokens that might be direct, only collection-derived ones
                
                new_tokens = [t for t in node_tokens if t not in tokens_to_remove]
                
                db.command(
                    f"UPDATE {node_label} SET acl_tokens = :tokens WHERE uid = :uid AND owner_id = :owner",
                    {"tokens": sorted(set(new_tokens)), "uid": node_id, "owner": owner_id},
                )
            
            return {
                "success": True,
                "node_id": node_id,
                "collection_id": collection_id,
                "deleted": len(result) if result else 0,
            }
    except Exception as exc:
        logger.error("Failed to remove node %s from collection %s: %s", node_id, collection_id, exc)
        return {
            "success": False,
            "error": str(exc),
            "code": "memory_service_error",
        }


def list_collections(
    db: Any,
    owner_id: str,
    viewer_id: str,
    limit: int = 50,
) -> Dict:
    """List collections visible to viewer (ACL-filtered).
    
    Returns:
        List of collections the viewer can access
    """
    try:
        # Compute viewer's ACL tokens
        from graph_memory_mcp.graph_memory.backends.arcade_ops import expand_principal_tokens
        
        viewer_tokens = expand_principal_tokens(db, viewer_id, owner_id)
        
        with db.owner_scope(owner_id):
            # Find all collections where acl_tokens intersect viewer_tokens
            if db.shared_graph:
                # ACL filtering
                collections = []
                all_colls = db.query(
                    f"SELECT uid, text, description, metadata_str, acl_tokens FROM Collection WHERE owner_id = :owner",
                    {"owner": owner_id},
                )
                for coll in all_colls:
                    coll_tokens = coll.get("acl_tokens") or []
                    if "ALL" in coll_tokens or any(t in viewer_tokens for t in coll_tokens):
                        collections.append({
                            "collection_id": coll.get("uid"),
                            "name": coll.get("text"),
                            "description": coll.get("description"),
                            "metadata": coll.get("metadata_str"),
                        })
                collections = collections[:int(limit)]
            else:
                # No ACL in per-owner mode
                rows = db.query(
                    f"SELECT uid, text, description, metadata_str FROM Collection WHERE owner_id = :owner LIMIT {int(limit)}",
                    {"owner": owner_id},
                )
                collections = [
                    {
                        "collection_id": row.get("uid"),
                        "name": row.get("text"),
                        "description": row.get("description"),
                        "metadata": row.get("metadata_str"),
                    }
                    for row in rows
                ]
        
        return {
            "success": True,
            "collections": collections,
            "count": len(collections),
        }
    except Exception as exc:
        logger.error("Failed to list collections: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "code": "memory_service_error",
        }


def get_collection_contents(
    db: Any,
    collection_id: str,
    owner_id: str,
    viewer_id: str,
    depth: int = 1,
    limit: int = 50,
) -> Dict:
    """Get nodes in a collection (ACL-filtered, depth=traversal depth).
    
    Args:
        collection_id: Collection to retrieve
        owner_id: Owner scope
        viewer_id: Viewer for ACL checks
        depth: How many hops via CONTAINS (1 = direct children only)
        limit: Max nodes to return
        
    Returns:
        Dict with nodes array and metadata
    """
    try:
        # Check viewer can access this collection
        from graph_memory_mcp.graph_memory.backends.arcade_ops import expand_principal_tokens, _rid
        
        viewer_tokens = set(expand_principal_tokens(db, viewer_id, owner_id))
        
        with db.owner_scope(owner_id):
            # Check collection exists and is visible
            coll_rec = db.query(
                f"SELECT uid, acl_tokens FROM Collection WHERE uid = :uid AND owner_id = :owner LIMIT 1",
                {"uid": collection_id, "owner": owner_id},
            )
            if not coll_rec:
                return {
                    "success": False,
                    "error": "Collection not found",
                    "code": "memory_not_found",
                }
            
            coll_tokens = coll_rec[0].get("acl_tokens") or []
            if db.shared_graph and "ALL" not in coll_tokens and not any(t in viewer_tokens for t in coll_tokens):
                return {
                    "success": False,
                    "error": "Access denied",
                    "code": "memory_access_denied",
                }
            
            # BFS from collection via CONTAINS edges
            coll_rid = _rid(coll_rec[0].get("@rid"))
            visited = set()
            current = [coll_rid]
            nodes = []
            
            for _d in range(max(1, int(depth))):
                next_wave = []
                for rid in current:
                    # Get outgoing CONTAINS edges
                    edges = db.query(
                        f"SELECT expand(out('CONTAINS')) FROM Collection WHERE @rid = {rid}"
                    )
                    for edge in edges:
                        node_rid = str(edge.get("@rid"))
                        if node_rid in visited:
                            continue
                        visited.add(node_rid)
                        
                        # Check ACL
                        node_tokens = edge.get("acl_tokens") or []
                        if db.shared_graph and "ALL" not in node_tokens and not any(t in viewer_tokens for t in node_tokens):
                            continue
                        
                        nodes.append({
                            "node_id": edge.get("uid"),
                            "node_type": edge.get("@type"),
                            "text": edge.get("text"),
                            "status": edge.get("status"),
                            "created_at": edge.get("created_at"),
                        })
                        
                        if len(nodes) >= int(limit):
                            break
                        
                        # If it's another collection, traverse it next
                        if edge.get("@type") == "Collection":
                            next_wave.append(node_rid)
                    
                    if len(nodes) >= int(limit):
                        break
                
                if len(nodes) >= int(limit):
                    break
                current = next_wave
                if not current:
                    break
        
        return {
            "success": True,
            "collection_id": collection_id,
            "nodes": nodes[:int(limit)],
            "count": len(nodes[:int(limit)]),
        }
    except Exception as exc:
        logger.error("Failed to get collection contents: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "code": "memory_service_error",
        }


def share_collection(
    db: Any,
    collection_id: str,
    owner_id: str,
    viewer_id: str,
    share_with_ids: List[str],
) -> Dict:
    """Share a collection with users/projects (add HAS_ACCESS edges).
    
    Recursively updates acl_tokens of collection and all contained nodes.
    
    Args:
        collection_id: Collection to share
        owner_id: Owner scope
        viewer_id: Who is sharing (must be owner or have access)
        share_with_ids: List of user:id, proj:id, or ALL
        
    Returns:
        Success dict with created edges
    """
    try:
        # Check viewer owns or has access to collection
        from graph_memory_mcp.graph_memory.backends.arcade_ops import expand_principal_tokens
        
        viewer_tokens = expand_principal_tokens(db, viewer_id, owner_id)
        
        with db.owner_scope(owner_id):
            coll_rec = db.query(
                f"SELECT acl_tokens FROM Collection WHERE uid = :uid AND owner_id = :owner LIMIT 1",
                {"uid": collection_id, "owner": owner_id},
            )
            if not coll_rec:
                return {
                    "success": False,
                    "error": "Collection not found",
                    "code": "memory_not_found",
                }
            
            coll_tokens = coll_rec[0].get("acl_tokens") or []
            # Only owner can share
            if f"owner:{owner_id}" not in viewer_tokens:
                return {
                    "success": False,
                    "error": "Only owner can share collections",
                    "code": "memory_access_denied",
                }
            
            # Create HAS_ACCESS edges and update ACL tokens
            from graph_memory_mcp.graph_memory.backends.arcade_ops import _rid, compute_acl_tokens
            
            coll_rid = _rid(coll_rec[0].get("@rid"))
            now_ms = int(__import__("time").time() * 1000)
            
            created = []
            for share_id in share_with_ids:
                # Add to ACL tokens
                if share_id not in coll_tokens:
                    coll_tokens.append(share_id)
                
                # Create HAS_ACCESS edge if it's a user or project node
                if share_id.startswith("user:"):
                    user_id = share_id[5:]
                    user_rec = db.query(
                        f"SELECT FROM User WHERE text = :user_id AND owner_id = :owner LIMIT 1",
                        {"user_id": user_id, "owner": owner_id},
                    )
                    if user_rec:
                        user_rid = _rid(user_rec[0].get("@rid"))
                        # Check if edge already exists
                        existing = db.query(
                            f"SELECT FROM HAS_ACCESS WHERE @out = {user_rid} AND @in = {coll_rid} LIMIT 1"
                        )
                        if not existing:
                            db.command(
                                f"CREATE EDGE HAS_ACCESS FROM {user_rid} TO {coll_rid} SET created_at = {now_ms}"
                            )
                        created.append(f"user:{user_id}")
                elif share_id.startswith("proj:"):
                    # Similar for projects
                    proj_id = share_id[5:]
                    proj_rec = db.query(
                        f"SELECT FROM Project WHERE uid = :proj_id AND owner_id = :owner LIMIT 1",
                        {"proj_id": proj_id, "owner": owner_id},
                    )
                    if proj_rec:
                        proj_rid = _rid(proj_rec[0].get("@rid"))
                        existing = db.query(
                            f"SELECT FROM HAS_ACCESS WHERE @out = {proj_rid} AND @in = {coll_rid} LIMIT 1"
                        )
                        if not existing:
                            db.command(
                                f"CREATE EDGE HAS_ACCESS FROM {proj_rid} TO {coll_rid} SET created_at = {now_ms}"
                            )
                        created.append(f"proj:{proj_id}")
                elif share_id == "ALL":
                    created.append("ALL")
            
            # Update collection ACL tokens
            if db.shared_graph:
                new_coll_tokens = sorted(set(coll_tokens))
                db.command(
                    f"UPDATE Collection SET acl_tokens = :tokens WHERE uid = :uid AND owner_id = :owner",
                    {"tokens": new_coll_tokens, "uid": collection_id, "owner": owner_id},
                )
                
                # Recursively propagate to all nodes in CONTAINS tree
                _propagate_collection_tokens(db, coll_rid, new_coll_tokens, owner_id)
        
        return {
            "success": True,
            "collection_id": collection_id,
            "shared_with": created,
            "count": len(created),
        }
    except Exception as exc:
        logger.error("Failed to share collection: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "code": "memory_service_error",
        }


def _propagate_collection_tokens(
    db: Any,
    coll_rid: str,
    coll_tokens: list[str],
    owner_id: str,
) -> None:
    """Recursively propagate collection's ACL tokens to all contained nodes.
    
    Args:
        db: Database client
        coll_rid: Collection RID
        coll_tokens: Tokens to propagate
        owner_id: Owner scope
    """
    # Get all nodes directly contained by this collection
    contained = db.query(
        f"SELECT expand(out('CONTAINS')) FROM Collection WHERE @rid = {coll_rid}"
    )
    
    for node in contained:
        node_type = node.get("@type")
        node_uid = node.get("uid")
        node_tokens = node.get("acl_tokens") or []
        
        # Merge tokens
        new_tokens = sorted(set(node_tokens + coll_tokens))
        
        # Update node
        db.command(
            f"UPDATE {node_type} SET acl_tokens = :tokens WHERE uid = :uid AND owner_id = :owner",
            {"tokens": new_tokens, "uid": node_uid, "owner": owner_id},
        )
        
        # If this node is also a collection, recurse
        if node_type == "Collection":
            from graph_memory_mcp.graph_memory.backends.arcade_ops import _rid
            sub_coll_rid = _rid(node.get("@rid"))
            _propagate_collection_tokens(db, sub_coll_rid, coll_tokens, owner_id)


def create_relation_with_weight(
    db: Any,
    from_id: str,
    to_id: str,
    relation_type: str,
    owner_id: str,
    weight: Optional[float] = None,
    properties: Optional[Dict] = None,
) -> Dict:
    """Create a weighted relation (extended create_relation).
    
    Args:
        from_id, to_id: Node UIDs
        relation_type: Edge type
        owner_id: Owner scope
        weight: Optional edge weight (0-1)
        properties: Additional edge properties
        
    Returns:
        Success dict with relation info
    """
    try:
        props = dict(properties or {})
        if weight is not None:
            props["weight"] = float(weight)
        
        rows = db.merge_relation(
            rel_type=relation_type,
            params={
                "from_id": from_id,
                "to_id": to_id,
                "owner_id": owner_id,
                **props,
            },
            prop_assignments=", " + ", ".join(f"r.{k} = ${k}" for k in props) if props else "",
        )
        
        return {
            "success": True,
            "from_id": from_id,
            "to_id": to_id,
            "relation_type": relation_type,
            "weight": weight,
            "relation_created": bool(rows),
        }
    except Exception as exc:
        logger.error("Failed to create weighted relation: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "code": "memory_service_error",
        }


def update_relation_weight(
    db: Any,
    from_id: str,
    to_id: str,
    relation_type: str,
    owner_id: str,
    weight: float,
) -> Dict:
    """Update weight of an existing relation.
    
    Returns:
        Success dict
    """
    try:
        with db.owner_scope(owner_id):
            from graph_memory_mcp.graph_memory.backends.arcade_ops import _rid
            
            from_rec = db.query(
                f"SELECT FROM Fact WHERE uid = :uid AND owner_id = :owner LIMIT 1",
                {"uid": from_id, "owner": owner_id},
            )
            if not from_rec:
                from_rec = db.query(
                    f"SELECT FROM Entity WHERE uid = :uid AND owner_id = :owner LIMIT 1",
                    {"uid": from_id, "owner": owner_id},
                )
            
            to_rec = db.query(
                f"SELECT FROM Fact WHERE uid = :uid AND owner_id = :owner LIMIT 1",
                {"uid": to_id, "owner": owner_id},
            )
            if not to_rec:
                to_rec = db.query(
                    f"SELECT FROM Entity WHERE uid = :uid AND owner_id = :owner LIMIT 1",
                    {"uid": to_id, "owner": owner_id},
                )
            
            if not from_rec or not to_rec:
                return {
                    "success": False,
                    "error": "Nodes not found",
                    "code": "memory_not_found",
                }
            
            from_rid = _rid(from_rec[0].get("@rid"))
            to_rid = _rid(to_rec[0].get("@rid"))
            
            # Find and update edge
            db.ensure_edge_type(relation_type)
            result = db.command(
                f"UPDATE {relation_type} SET weight = :weight WHERE @out = {from_rid} AND @in = {to_rid}",
                {"weight": float(weight)},
            )
            
            return {
                "success": True,
                "from_id": from_id,
                "to_id": to_id,
                "relation_type": relation_type,
                "weight": weight,
                "updated": len(result) if result else 0,
            }
    except Exception as exc:
        logger.error("Failed to update relation weight: %s", exc)
        return {
            "success": False,
            "error": str(exc),
            "code": "memory_service_error",
        }
