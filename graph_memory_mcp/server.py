"""
MCP Graph Memory server (FalkorDB Graph Database).

Layers:
- MCP layer (this file): MCP tools registration only (thin wrapper);
- handlers layer: high-level business logic in `graph_memory_mcp.graph_memory.mcp_handlers`;
- DB layer: `graph_memory_mcp.graph_memory.database.FalkorDBClient`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from mcp.types import ToolAnnotations

from graph_memory_mcp.base_server import BaseGraphMemoryMCP
from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory import (
    mcp_handlers_admin,
    mcp_handlers_graph,
    mcp_handlers_nodes,
    mcp_handlers_relations,
    mcp_handlers_search,
)

logger = logging.getLogger(__name__)


class GraphMemoryMCP(BaseGraphMemoryMCP):
    """Graph Memory MCP Server: builds FastMCP app and registers tools."""

    def __init__(self, server_config: MCPServerConfig):
        super().__init__(server_config)

        # Auto-create vector indices if enabled (opt-in)
        if self.server_config.auto_create_indexes and self._db_connected:
            logger.info(
                "AUTO-CREATE: Creating vector indexes (config.auto_create_indexes=true)"
            )
            try:
                self._ensure_indexes_if_needed()
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to auto-create vector indexes: %s", exc)

    def _ensure_indexes_if_needed(self) -> None:
        """Create vector indexes if they don't exist (with dimension validation)."""
        dim = int(getattr(self.embedding_service, "dimension", 0) or 0)
        if dim <= 0:
            logger.warning("Cannot create indexes: embedding dimension is %s", dim)
            return

        status = self.db_client.get_vector_index_status()
        fact_ok = bool(status.get("Fact"))
        ent_ok = bool(status.get("Entity"))

        if not fact_ok:
            logger.info("Creating Fact vector index (dimension=%s)", dim)
            self.db_client.create_vector_index(
                dimension=dim, similarity_function="cosine"
            )
        if not ent_ok:
            logger.info("Creating Entity vector index (dimension=%s)", dim)
            self.db_client.create_entity_vector_index(
                dimension=dim, similarity_function="cosine"
            )

    def _register_tools(self) -> None:
        exposed: Dict[str, Any] = {}
        exposed.update(self._register_information_tools())
        exposed.update(self._register_fact_tools())
        exposed.update(self._register_triplet_tools())
        exposed.update(self._register_graph_tools())

        for attr, func in exposed.items():
            setattr(self, attr, func)

    def _register_information_tools(self) -> Dict[str, Any]:
        exposed: Dict[str, Any] = {}
        db = self.db_client
        mcp = self.mcp
        assert mcp is not None

        @mcp.tool(
            title="Test connection",
            description="Simple ping to verify MCP server availability.",
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def test_connection() -> dict:
            return mcp_handlers_admin.test_connection(db)

        @mcp.tool(
            title="Get stats",
            description="Get graph statistics (node counts, etc.).",
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def get_stats(owner_id: str = "default") -> dict:
            return mcp_handlers_admin.get_stats(db, owner_id=owner_id)

        @mcp.tool(
            title="Health check",
            description="Check server health (FalkorDB, embeddings, vector index).",
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def health_check() -> dict:
            return mcp_handlers_admin.health_check(db, self.embedding_service)

        @mcp.tool(
            title="Ensure vector indexes",
            description=(
                "Create or verify vector indexes for semantic search. "
                "Idempotent - safe to call multiple times. "
                "Validates embedding dimension compatibility. "
                "Required before using search or auto_link features."
            ),
        )
        def ensure_vector_indexes() -> dict:
            try:
                self._ensure_indexes_if_needed()
                status = db.get_vector_index_status()
                return {
                    "success": True,
                    "indexes": status,
                    "dimension": getattr(self.embedding_service, "dimension", 0),
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

        exposed["test_connection"] = test_connection
        exposed["get_stats"] = get_stats
        exposed["health_check"] = health_check
        exposed["ensure_vector_indexes"] = ensure_vector_indexes
        return exposed

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
                "`metadata`, `auto_link` (Facts only), `ttl_days` (Facts only), "
                "`links` (create relations immediately after creation). "
                "Note: auto_link=true by default creates semantic MENTIONS_ENTITY relations to existing entities (Facts only). "
                "Set ttl_days for automatic archival."
            ),
        )
        def create_node(
            text: str | None = None,
            node_type: str = "Fact",
            owner_id: str = "default",
            metadata: dict | None = None,
            status: str | None = None,
            ttl_days: float | None = None,
            entity_type: str | None = None,
            auto_link: bool = True,
            semantic_threshold: float | None = None,
            links: list[dict] | None = None,
        ) -> dict:
            return mcp_handlers_nodes.create_node(
                db,
                config,
                text=text,
                node_type=node_type,
                owner_id=owner_id,
                metadata=metadata,
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
                "Returns active nodes by default (use include_outdated=true for archived content). "
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
                "You can update text, metadata, status, or ttl_days."
            ),
        )
        def update_node(
            node_id: str,
            owner_id: str = "default",
            text: str | None = None,
            metadata: dict | None = None,
            status: str | None = None,
            ttl_days: float | None = None,
            entity_type: str | None = None,
            versioning: bool = False,
        ) -> dict:
            return mcp_handlers_nodes.update_node(
                db,
                node_id=node_id,
                owner_id=owner_id,
                text=text,
                metadata=metadata,
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
                "Returns a list of previous versions with timestamps"
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

    def _register_triplet_tools(self) -> Dict[str, Any]:
        exposed: Dict[str, Any] = {}
        db = self.db_client
        mcp = self.mcp
        assert mcp is not None

        @mcp.tool(
            title="Create triplet",
            description=(
                "Create a subject-predicate-object triplet. "
                "Entities are created if they don't exist. "
                "Optional: link to a source fact_id."
            ),
        )
        def create_triplet(
            subject: str,
            predicate: str,
            object_value: str,
            metadata: dict | None = None,
            fact_id: str | None = None,
            owner_id: str = "default",
        ) -> dict:
            return mcp_handlers_relations.create_triplet(
                db,
                subject=subject,
                predicate=predicate,
                object_value=object_value,
                metadata=metadata,
                fact_id=fact_id,
                owner_id=owner_id,
            )

        @mcp.tool(
            title="Search triplets",
            description=(
                "Search for triplets matching a pattern. "
                "All parameters are optional; omit to match any value."
            ),
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def search_triplets(
            subject: str | None = None,
            predicate: str | None = None,
            object_value: str | None = None,
            owner_id: str = "default",
            limit: int = 10,
        ) -> dict:
            return mcp_handlers_relations.search_triplets(
                db,
                subject=subject,
                predicate=predicate,
                object_value=object_value,
                owner_id=owner_id,
                limit=limit,
            )

        exposed["create_triplet"] = create_triplet
        exposed["search_triplets"] = search_triplets
        return exposed

    def _register_graph_tools(self) -> Dict[str, Any]:
        exposed: Dict[str, Any] = {}
        db = self.db_client
        config = self.config
        mcp = self.mcp
        assert mcp is not None

        @mcp.tool(
            title="Create relation",
            description=(
                "Create a direct relation between two nodes. "
                "Both nodes must exist. "
                "Use this for explicit graph structure. "
                "For semantic auto-linking, see create_node with auto_link=true."
            ),
        )
        def create_relation(
            from_id: str,
            to_id: str,
            relation_type: str,
            properties: dict | None = None,
            owner_id: str = "default",
        ) -> dict:
            return mcp_handlers_relations.create_relation(
                db,
                from_id=from_id,
                to_id=to_id,
                relation_type=relation_type,
                properties=properties,
                owner_id=owner_id,
            )

        @mcp.tool(
            title="Get trace",
            description=(
                "Find shortest path between two nodes. "
                "Returns the path as a sequence of nodes and relations."
            ),
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def get_trace(
            from_id: str,
            to_id: str,
            owner_id: str = "default",
            max_depth: int = 5,
        ) -> dict:
            return mcp_handlers_graph.get_trace(
                db, from_id=from_id, to_id=to_id, owner_id=owner_id, max_depth=max_depth
            )

        @mcp.tool(
            title="Delete relation",
            description=(
                "Remove relations between two nodes. "
                "Optionally specify relation_type to remove only specific relations. "
                "Works for any node types (Fact, Entity)."
            ),
        )
        def delete_relation(
            from_id: str,
            to_id: str,
            relation_type: str | None = None,
            owner_id: str = "default",
        ) -> dict:
            return mcp_handlers_relations.unlink_facts(
                db,
                from_id=from_id,
                to_id=to_id,
                relation_type=relation_type,
                owner_id=owner_id,
            )

        @mcp.tool(
            title="Get context",
            description=(
                "Get subgraph context around a node. "
                "Returns nodes and edges within specified depth. "
                "Useful for building agent context from related facts and entities. "
                "Depth defaults to 2 hops."
            ),
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def get_context(
            node_id: str,
            owner_id: str = "default",
            depth: int | None = None,
            max_nodes: int | None = None,
        ) -> dict:
            return mcp_handlers_graph.get_context(
                db,
                config,
                node_id=node_id,
                owner_id=owner_id,
                depth=depth,
                max_nodes=max_nodes,
            )

        @mcp.tool(
            title="Find similar",
            description=(
                "Find facts similar to a given fact using embedding similarity. "
                "Returns facts ranked by semantic similarity (excludes the query fact itself). "
                "Useful for discovering related knowledge or identifying potential duplicates."
            ),
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def find_similar(
            fact_id: str,
            owner_id: str = "default",
            limit: int = 5,
            similarity_threshold: float | None = None,
        ) -> dict:
            return mcp_handlers_search.find_similar(
                db,
                config,
                fact_id=fact_id,
                owner_id=owner_id,
                limit=limit,
                similarity_threshold=similarity_threshold,
            )

        @mcp.tool(
            title="Create summary fact",
            description=(
                "Create a summary fact from multiple source facts. "
                "Links the summary to all source facts."
            ),
        )
        def create_summary_fact(
            fact_ids: list[str],
            summary_text: str,
            owner_id: str = "default",
            metadata: dict | None = None,
        ) -> dict:
            return mcp_handlers_admin.create_summary_fact(
                db,
                config,
                fact_ids=fact_ids,
                summary_text=summary_text,
                owner_id=owner_id,
                metadata=metadata,
            )

        exposed["create_relation"] = create_relation
        exposed["delete_relation"] = delete_relation
        exposed["get_trace"] = get_trace
        exposed["get_context"] = get_context
        exposed["find_similar"] = find_similar
        exposed["create_summary_fact"] = create_summary_fact

        return exposed
