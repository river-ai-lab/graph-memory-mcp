"""MCP Graph Memory Extended Server (Multi-tenant with Collections).

Same tools as the default server, plus description, shared_with_ids,
collection_id, and node types Collection, User, and Project.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory import mcp_handlers_atlas, mcp_handlers_nodes
from graph_memory_mcp.server import GraphMemoryMCP

logger = logging.getLogger(__name__)


class GraphMemoryExtendedMCP(GraphMemoryMCP):
    """Default tools, plus collections, sharing, and Collection / User / Project nodes."""

    def __init__(self, server_config: MCPServerConfig):
        # Extended server requires ArcadeDB backend
        if server_config.graph_backend != "arcadedb":
            raise ValueError(
                "Extended server (Atlas) requires GRAPH_BACKEND=arcadedb. "
                "The simple server works with any backend. "
                "Set GRAPH_BACKEND=arcadedb and ARCADE_SHARED_GRAPH=true in your .env"
            )
        super().__init__(server_config)
        logger.info(
            "GraphMemoryExtendedMCP: like GraphMemoryMCP; "
            "writes also take description, shared_with_ids, collection_id; "
            "backend=%s, shared_graph=%s",
            server_config.graph_backend,
            getattr(server_config, "arcade_shared_graph", False),
        )
        # Register Atlas-specific tools
        self._register_atlas_tools()

    def _register_atlas_tools(self) -> None:
        """Register collection and access control tools."""
        exposed: Dict[str, Any] = {}
        db = self.db_client
        mcp = self.mcp
        assert mcp is not None
        default_owner = self.config.default_owner_id

        @mcp.tool(
            title="Add to collection",
            description=(
                "Add a node to a collection (creates CONTAINS edge). "
                "Required: node_id, collection_id, owner_id. "
                "The node and collection must exist."
            ),
        )
        def add_to_collection(
            node_id: str,
            collection_id: str,
            owner_id: str = default_owner,
        ) -> dict:
            return mcp_handlers_atlas.add_to_collection(
                db, node_id, collection_id, owner_id
            )

        @mcp.tool(
            title="Remove from collection",
            description=(
                "Remove a node from a collection (deletes CONTAINS edge). "
                "Required: node_id, collection_id, owner_id."
            ),
        )
        def remove_from_collection(
            node_id: str,
            collection_id: str,
            owner_id: str = default_owner,
        ) -> dict:
            return mcp_handlers_atlas.remove_from_collection(
                db, node_id, collection_id, owner_id
            )

        @mcp.tool(
            title="List collections",
            description=(
                "List collections visible to the viewer (ACL-filtered). "
                "Required: viewer_id (the user requesting the list). "
                "Returns collections the viewer can access."
            ),
        )
        def list_collections(
            viewer_id: str,
            owner_id: str = default_owner,
            limit: int = 50,
        ) -> dict:
            return mcp_handlers_atlas.list_collections(
                db, owner_id, viewer_id, limit
            )

        @mcp.tool(
            title="Get collection contents",
            description=(
                "Get nodes in a collection (ACL-filtered, with depth traversal). "
                "Required: collection_id, viewer_id. "
                "Optional: depth (how many CONTAINS hops, default 1), limit (max nodes). "
                "Returns nodes the viewer can access."
            ),
        )
        def get_collection_contents(
            collection_id: str,
            viewer_id: str,
            owner_id: str = default_owner,
            depth: int = 1,
            limit: int = 50,
        ) -> dict:
            return mcp_handlers_atlas.get_collection_contents(
                db, collection_id, owner_id, viewer_id, depth, limit
            )

        @mcp.tool(
            title="Share collection",
            description=(
                "Share a collection with users/projects (creates HAS_ACCESS edges). "
                "Required: collection_id, viewer_id (must be owner), share_with_ids. "
                "share_with_ids: list of 'user:id', 'proj:id', or 'ALL' for public access."
            ),
        )
        def share_collection(
            collection_id: str,
            viewer_id: str,
            share_with_ids: list[str],
            owner_id: str = default_owner,
        ) -> dict:
            return mcp_handlers_atlas.share_collection(
                db, collection_id, owner_id, viewer_id, share_with_ids
            )

        @mcp.tool(
            title="Create weighted relation",
            description=(
                "Create a relation with an optional weight (0-1). "
                "Required: from_id, to_id, relation_type, owner_id. "
                "Optional: weight (edge weight), properties (additional edge data)."
            ),
        )
        def create_relation_ext(
            from_id: str,
            to_id: str,
            relation_type: str,
            owner_id: str = default_owner,
            weight: float | None = None,
            properties: dict | None = None,
        ) -> dict:
            return mcp_handlers_atlas.create_relation_with_weight(
                db, from_id, to_id, relation_type, owner_id, weight, properties
            )

        @mcp.tool(
            title="Update relation weight",
            description=(
                "Update the weight of an existing relation. "
                "Required: from_id, to_id, relation_type, weight, owner_id."
            ),
        )
        def update_relation_weight(
            from_id: str,
            to_id: str,
            relation_type: str,
            weight: float,
            owner_id: str = default_owner,
        ) -> dict:
            return mcp_handlers_atlas.update_relation_weight(
                db, from_id, to_id, relation_type, owner_id, weight
            )

        exposed["add_to_collection"] = add_to_collection
        exposed["remove_from_collection"] = remove_from_collection
        exposed["list_collections"] = list_collections
        exposed["get_collection_contents"] = get_collection_contents
        exposed["share_collection"] = share_collection
        exposed["create_relation_ext"] = create_relation_ext
        exposed["update_relation_weight"] = update_relation_weight

        for attr, func in exposed.items():
            setattr(self, attr, func)

    def _register_node_write_tools(self) -> Dict[str, Any]:
        """Same create/upsert/update as the default server, plus extended fields."""
        exposed: Dict[str, Any] = {}
        db = self.db_client
        config = self.config
        mcp = self.mcp
        assert mcp is not None
        default_owner = self.config.default_owner_id

        @mcp.tool(
            title="Create node",
            description=(
                "Create a node (Fact, Entity, Collection, User, or Project). "
                "Required: `text`, "
                "Optional: `node_type` ('Fact' default, or Entity, Collection, User, Project), `owner_id`, "
                "`metadata`, `description` (longer text beside `text`), "
                "`shared_with_ids` (who may see the node), "
                "`collection_id` (CONTAINS edge to that collection), "
                "`source` (provenance dict with keys like ref/type/uri/content_hash/updated_at/version), "
                "`auto_link` (Facts only), `ttl_days` (Facts only), "
                "`links` (create relations immediately after creation). "
                "Note: auto_link defaults to false. Pass true on a Fact to add MENTIONS edges to similar Entity nodes "
                "(vector search on Entity index; threshold AUTO_LINKING_SEMANTIC_THRESHOLD). "
                "Use create_relation for links between arbitrary node pairs. "
                "Set ttl_days for a temporary fact (the server never assigns it). "
                "After expires_at the archive job sets status=archived. "
                "`check_duplicates` (default true) blocks a near-paraphrase before write. "
                "Pass false when the nearby fact is similar by distance but is a different fact. "
                "A very long text is warned in `warnings` and still stored."
            ),
        )
        def create_node(
            text: str,
            node_type: Literal[
                "Fact", "Entity", "Collection", "User", "Project"
            ] = "Fact",
            owner_id: str = default_owner,
            metadata: dict | None = None,
            description: str | None = None,
            shared_with_ids: list[str] | None = None,
            collection_id: str | None = None,
            source: dict | None = None,
            status: Literal["active", "outdated", "archived"] | None = None,
            ttl_days: float | None = None,
            entity_type: str | None = None,
            auto_link: bool = False,
            semantic_threshold: float | None = None,
            links: list[dict] | None = None,
            check_duplicates: bool = True,
        ) -> dict:
            return mcp_handlers_nodes.create_node(
                db,
                config,
                text=text,
                description=description,
                node_type=node_type,
                owner_id=owner_id,
                shared_with_ids=shared_with_ids,
                collection_id=collection_id,
                metadata=metadata,
                source=source,
                status=status,
                ttl_days=ttl_days,
                entity_type=entity_type,
                auto_link=auto_link,
                semantic_threshold=semantic_threshold,
                links=links,
                check_duplicates=check_duplicates,
            )

        @mcp.tool(
            title="Upsert node",
            description=(
                "Create or update a node using `source.ref` as a stable sync key. "
                "Required: `text`, `source.ref`. "
                "Optional: same fields as create_node, including `description`, "
                "`shared_with_ids`, and `collection_id`, plus `versioning=true` to store "
                "a version snapshot and auto-increment `source.version` when it is omitted. "
                "No `check_duplicates`: this updates the node for that ref."
            ),
        )
        def upsert_node(
            text: str,
            source: dict,
            node_type: Literal[
                "Fact", "Entity", "Collection", "User", "Project"
            ] = "Fact",
            owner_id: str = default_owner,
            metadata: dict | None = None,
            description: str | None = None,
            shared_with_ids: list[str] | None = None,
            collection_id: str | None = None,
            status: Literal["active", "outdated", "archived"] | None = None,
            ttl_days: float | None = None,
            versioning: bool | None = None,
            entity_type: str | None = None,
            auto_link: bool = False,
            semantic_threshold: float | None = None,
            links: list[dict] | None = None,
        ) -> dict:
            return mcp_handlers_nodes.upsert_node(
                db,
                config,
                text=text,
                description=description,
                node_type=node_type,
                owner_id=owner_id,
                shared_with_ids=shared_with_ids,
                collection_id=collection_id,
                metadata=metadata,
                source=source,
                status=status,
                ttl_days=ttl_days,
                versioning=versioning,
                entity_type=entity_type,
                auto_link=auto_link,
                semantic_threshold=semantic_threshold,
                links=links,
            )

        @mcp.tool(
            title="Update node",
            description=(
                "Update a node (Fact or Entity). "
                "You can update text, description, shared_with_ids, metadata, source, status, or ttl_days. "
                "Set versioning=true to store a previous snapshot and auto-increment source.version when it is omitted."
            ),
        )
        def update_node(
            node_id: str,
            owner_id: str = default_owner,
            text: str | None = None,
            description: str | None = None,
            shared_with_ids: list[str] | None = None,
            metadata: dict | None = None,
            source: dict | None = None,
            status: Literal["active", "outdated", "archived"] | None = None,
            ttl_days: float | None = None,
            entity_type: str | None = None,
            versioning: bool | None = None,
        ) -> dict:
            return mcp_handlers_nodes.update_node(
                db,
                node_id=node_id,
                owner_id=owner_id,
                text=text,
                description=description,
                shared_with_ids=shared_with_ids,
                metadata=metadata,
                source=source,
                status=status,
                ttl_days=ttl_days,
                entity_type=entity_type,
                versioning=versioning,
            )

        exposed["create_node"] = create_node
        exposed["upsert_node"] = upsert_node
        exposed["update_node"] = update_node
        return exposed
