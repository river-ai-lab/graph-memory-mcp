"""
MCP Graph Memory server — same as `graph_memory_mcp.server.GraphMemoryMCP` for
operators who prefer not to pass a nested `source` object on MCP tools.

No `upsert_node` tool (use the full `GraphMemoryMCP` if you need sync-by-ref).

Handlers and DB behavior are unchanged: optional provenance is forwarded as a
`source` dict built from flat parameters (`ref`, `provenance_type`, `uri`, …).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from mcp.types import ToolAnnotations

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory import (
    mcp_handlers_nodes,
    mcp_handlers_search,
)
from graph_memory_mcp.server import GraphMemoryMCP

logger = logging.getLogger(__name__)


def _provenance_source(
    *,
    ref: str | None = None,
    provenance_type: str | None = None,
    uri: str | None = None,
    content_hash: str | None = None,
    updated_at: int | None = None,
    version: int | None = None,
) -> dict[str, Any] | None:
    """Build handler `source` dict from flat MCP fields (same keys as full server)."""
    parts: dict[str, Any] = {}
    if ref is not None:
        parts["ref"] = ref
    if provenance_type is not None:
        parts["type"] = provenance_type
    if uri is not None:
        parts["uri"] = uri
    if content_hash is not None:
        parts["content_hash"] = content_hash
    if updated_at is not None:
        parts["updated_at"] = updated_at
    if version is not None:
        parts["version"] = version
    return parts if parts else None


class GraphMemorySimpleMCP(GraphMemoryMCP):
    """Like `GraphMemoryMCP` with flat provenance fields; does not register `upsert_node`."""

    def __init__(self, server_config: MCPServerConfig):
        super().__init__(server_config)
        logger.info(
            "GraphMemorySimpleMCP: like GraphMemoryMCP but no upsert_node; provenance via flat fields (no `source` object)"
        )

    def _register_fact_tools(self) -> Dict[str, Any]:
        exposed: Dict[str, Any] = {}
        db = self.db_client
        config = self.config
        mcp = self.mcp
        assert mcp is not None

        @mcp.tool(
            title="Create node",
            description=(
                "Create a node (Fact or Entity). "
                "Required: `text`, "
                "Optional: `node_type` ('Fact' default, or 'Entity'), `owner_id`, "
                "`metadata`, "
                "optional provenance: `ref`, `provenance_type`, `uri`, `content_hash`, `updated_at`, `version` "
                "(same semantics as the full server's `source` object, without nesting), "
                "`auto_link` (Facts only), `ttl_days` (Facts only), "
                "`links` (create relations immediately after creation). "
                "Note: auto_link=true (default) on Facts adds MENTIONS to similar Entity nodes; "
                "use create_relation for other pairs. "
                "Set ttl_days for automatic archival."
            ),
        )
        def create_node(
            text: str,
            node_type: Literal["Fact", "Entity"] = "Fact",
            owner_id: str = "default",
            metadata: dict | None = None,
            ref: str | None = None,
            provenance_type: str | None = None,
            uri: str | None = None,
            content_hash: str | None = None,
            updated_at: int | None = None,
            version: int | None = None,
            status: Literal["active", "outdated", "archived"] | None = None,
            ttl_days: float | None = None,
            entity_type: str | None = None,
            auto_link: bool = True,
            semantic_threshold: float | None = None,
            links: list[dict] | None = None,
        ) -> dict:
            source = _provenance_source(
                ref=ref,
                provenance_type=provenance_type,
                uri=uri,
                content_hash=content_hash,
                updated_at=updated_at,
                version=version,
            )
            return mcp_handlers_nodes.create_node(
                db,
                config,
                text=text,
                node_type=node_type,
                owner_id=owner_id,
                metadata=metadata,
                source=source,
                status=status,
                ttl_days=ttl_days,
                entity_type=entity_type,
                auto_link=auto_link,
                semantic_threshold=semantic_threshold,
                links=links,
            )

        @mcp.tool(
            title="Search",
            description=(
                "Semantic search using embedding similarity (cosine distance). "
                "Returns active nodes by default (use include_outdated=true to include outdated and archived nodes). "
                "Results ranked by similarity to query text. "
                "Supports multi-tenant isolation via owner_id."
            ),
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def search(
            query: str,
            owner_id: str = "default",
            limit: int | None = None,
            node_types: list[str] | None = None,
            status: str | None = None,
            similarity_threshold: float | None = None,
            include_outdated: bool = False,
        ) -> dict:
            return mcp_handlers_search.search(
                db,
                config,
                query=query,
                owner_id=owner_id,
                limit=limit,
                node_types=node_types,
                status=status,
                similarity_threshold=similarity_threshold,
                include_outdated=include_outdated,
            )

        @mcp.tool(
            title="Get node",
            description="Retrieve a single node (Fact or Entity) by its ID.",
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def get_node(node_id: str, owner_id: str = "default") -> dict:
            return mcp_handlers_nodes.get_node(db, node_id=node_id, owner_id=owner_id)

        @mcp.tool(
            title="Update node",
            description=(
                "Update a node (Fact or Entity). "
                "You can update text, metadata, status, or ttl_days. "
                "Optional provenance updates use the same flat fields as create_node (`ref`, `provenance_type`, `uri`, "
                "`content_hash`, `updated_at`, `version`). "
                "Set versioning=true to store a previous snapshot and auto-increment version when it is omitted."
            ),
        )
        def update_node(
            node_id: str,
            owner_id: str = "default",
            text: str | None = None,
            metadata: dict | None = None,
            ref: str | None = None,
            provenance_type: str | None = None,
            uri: str | None = None,
            content_hash: str | None = None,
            updated_at: int | None = None,
            version: int | None = None,
            status: Literal["active", "outdated", "archived"] | None = None,
            ttl_days: float | None = None,
            entity_type: str | None = None,
            versioning: bool = False,
        ) -> dict:
            source = _provenance_source(
                ref=ref,
                provenance_type=provenance_type,
                uri=uri,
                content_hash=content_hash,
                updated_at=updated_at,
                version=version,
            )
            return mcp_handlers_nodes.update_node(
                db,
                node_id=node_id,
                owner_id=owner_id,
                text=text,
                metadata=metadata,
                source=source,
                status=status,
                ttl_days=ttl_days,
                entity_type=entity_type,
                versioning=versioning,
            )

        @mcp.tool(
            title="Delete node",
            description=(
                "PERMANENT: Irreversibly delete a node (Fact or Entity) and all its relations. "
                "This operation cannot be undone. "
                "For reversible removal of Facts, use mark_outdated instead."
            ),
        )
        def delete_node(node_id: str, owner_id: str = "default") -> dict:
            return mcp_handlers_nodes.delete_node(
                db, node_id=node_id, owner_id=owner_id
            )

        @mcp.tool(
            title="Mark fact as outdated",
            description=(
                "Soft-delete a Fact by setting status='outdated'. "
                "Fact remains in graph but excluded from default searches. "
                "Optionally stores reason in metadata. "
                "Note: Only Facts support soft-delete. For Entities, use delete_node."
            ),
        )
        def mark_outdated(
            fact_id: str, reason: str | None = None, owner_id: str = "default"
        ) -> dict:
            return mcp_handlers_nodes.mark_outdated(
                db, fact_id=fact_id, reason=reason, owner_id=owner_id
            )

        @mcp.tool(
            title="Get node change history",
            description=(
                "Retrieve version history for a node. "
                "Returns a list of previous versions with timestamps. "
                "Currently only supported for Fact nodes."
            ),
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def get_node_change_history(node_id: str, owner_id: str = "default") -> dict:
            return mcp_handlers_nodes.get_node_change_history(
                db, node_id=node_id, owner_id=owner_id
            )

        exposed["search"] = search
        exposed["create_node"] = create_node
        exposed["get_node"] = get_node
        exposed["update_node"] = update_node
        exposed["delete_node"] = delete_node
        exposed["mark_outdated"] = mark_outdated
        exposed["get_node_change_history"] = get_node_change_history

        return exposed
