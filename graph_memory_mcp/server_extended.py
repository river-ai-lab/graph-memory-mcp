"""MCP Graph Memory Extended Server (Multi-tenant with Collections).

Same tools as the default server, plus description, shared_with_ids,
collection_id, and node types Collection, User, and Project.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory import mcp_handlers_nodes
from graph_memory_mcp.server import GraphMemoryMCP

logger = logging.getLogger(__name__)


class GraphMemoryExtendedMCP(GraphMemoryMCP):
    """Default tools, plus collections, sharing, and Collection / User / Project nodes."""

    def __init__(self, server_config: MCPServerConfig):
        super().__init__(server_config)
        logger.info(
            "GraphMemoryExtendedMCP: like GraphMemoryMCP; "
            "writes also take description, shared_with_ids, collection_id"
        )

    def _register_node_write_tools(self) -> Dict[str, Any]:
        """Same create/upsert/update as the default server, plus extended fields."""
        exposed: Dict[str, Any] = {}
        db = self.db_client
        config = self.config
        mcp = self.mcp
        assert mcp is not None
        default_owner = self._tool_owner_default()

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
                "A very long text is warned in `warnings` and still stored. "
                f"{self._owner_tool_help()} {self._attribution_tool_help()}"
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
                "No `check_duplicates`: this updates the node for that ref. "
                f"{self._owner_tool_help()} {self._attribution_tool_help()}"
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
                "Set versioning=true to store a previous snapshot and auto-increment source.version when it is omitted. "
                f"{self._owner_tool_help()} {self._attribution_tool_help()}"
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
