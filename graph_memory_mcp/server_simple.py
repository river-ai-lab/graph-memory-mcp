"""
MCP Graph Memory server — same as `graph_memory_mcp.server.GraphMemoryMCP` for
operators who prefer not to pass a nested `source` object on MCP tools.

Handlers and DB behavior are unchanged: optional provenance is forwarded as a
`source` dict built from flat parameters (`ref`, `provenance_type`, `uri`, …).
Only the node write tools differ; everything else is inherited.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory import mcp_handlers_nodes
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
    """Like `GraphMemoryMCP` with flat provenance fields instead of a nested `source` dict."""

    def __init__(self, server_config: MCPServerConfig):
        super().__init__(server_config)
        logger.info(
            "GraphMemorySimpleMCP: like GraphMemoryMCP; provenance via flat fields (no `source` object)"
        )

    def _register_node_write_tools(self) -> Dict[str, Any]:
        """Flat-provenance create/upsert/update; shared node tools are inherited."""
        exposed: Dict[str, Any] = {}
        db = self.db_client
        config = self.config
        mcp = self.mcp
        assert mcp is not None
        default_owner = self.config.default_owner_id

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
                "Set ttl_days for automatic archival. "
                "Response may include possible_duplicates — review before keeping both."
            ),
        )
        def create_node(
            text: str,
            node_type: Literal["Fact", "Entity"] = "Fact",
            owner_id: str = default_owner,
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
            title="Upsert node",
            description=(
                "Create or update a node using `ref` as a stable sync key. "
                "Required: `text`, `ref`. "
                "Optional: same flat provenance fields as create_node (`provenance_type`, `uri`, "
                "`content_hash`, `updated_at`, `version`), plus `versioning=true` to store "
                "a version snapshot and auto-increment `version` when it is omitted."
            ),
        )
        def upsert_node(
            text: str,
            ref: str,
            node_type: Literal["Fact", "Entity"] = "Fact",
            owner_id: str = default_owner,
            metadata: dict | None = None,
            provenance_type: str | None = None,
            uri: str | None = None,
            content_hash: str | None = None,
            updated_at: int | None = None,
            version: int | None = None,
            status: Literal["active", "outdated", "archived"] | None = None,
            ttl_days: float | None = None,
            versioning: bool | None = None,
            entity_type: str | None = None,
            auto_link: bool = True,
            semantic_threshold: float | None = None,
            links: list[dict] | None = None,
            description: str | None = None,
        ) -> dict:
            source = _provenance_source(
                ref=ref,
                provenance_type=provenance_type,
                uri=uri,
                content_hash=content_hash,
                updated_at=updated_at,
                version=version,
            )
            return mcp_handlers_nodes.upsert_node(
                db,
                config,
                text=text,
                description=description,
                node_type=node_type,
                owner_id=owner_id,
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
                "You can update text, metadata, status, or ttl_days. "
                "Optional provenance updates use the same flat fields as create_node (`ref`, `provenance_type`, `uri`, "
                "`content_hash`, `updated_at`, `version`). "
                "Set versioning=true to store a previous snapshot and auto-increment version when it is omitted."
            ),
        )
        def update_node(
            node_id: str,
            owner_id: str = default_owner,
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
            versioning: bool | None = None,
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

        exposed["create_node"] = create_node
        exposed["upsert_node"] = upsert_node
        exposed["update_node"] = update_node
        return exposed
