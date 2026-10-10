"""
MCP Graph Memory Extended Server (Multi-tenant with Collections).

Extended version of server.py with multi-tenant support, collections,
and additional node fields (description, shared_with_ids).

Layers:
- MCP layer (this file): MCP tools registration (thin wrapper);
- handlers layer: business logic in `graph_memory_mcp.graph_memory.mcp_handlers*`;
- DB layer: `graph_memory_mcp.graph_memory.database.FalkorDBClient`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

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


class GraphMemoryExtendedMCP(BaseGraphMemoryMCP):
    """Extended Graph Memory MCP Server with multi-tenant and collection support."""

    def _register_tools(self) -> None:
        exposed: Dict[str, Any] = {}
        exposed.update(self._register_information_tools())
        exposed.update(self._register_extended_node_tools())
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
            description="Check server health (FalkorDB, embeddings).",
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def health_check() -> dict:
            return mcp_handlers_admin.health_check(db, self.embedding_service)

        exposed["test_connection"] = test_connection
        exposed["get_stats"] = get_stats
        exposed["health_check"] = health_check
        return exposed

    def _register_extended_node_tools(self) -> Dict[str, Any]:
        """Register extended node tools with description, shared_with_ids, collection_id."""
        exposed: Dict[str, Any] = {}
        db = self.db_client
        config = self.config
        mcp = self.mcp
        assert mcp is not None

        @mcp.tool(
            title="Create node (extended)",
            description=(
                "Create a node with extended fields (description, shared_with_ids, collection_id). "
                "Required: `text`, "
                "Optional: `description` (long-form content), `node_type` ('Fact' default, or 'Entity'), "
                "`owner_id`, `shared_with_ids` (list of user IDs), `collection_id`, "
                "`metadata`, `auto_link` (Facts only), `ttl_days` (Facts only), "
                "`links` (create relations immediately after creation). "
                "Note: auto_link defaults to false. Pass true on a Fact to add MENTIONS to similar Entity nodes; "
                "use create_relation for other pairs. "
            ),
        )
        def create_node_ext(
            text: str | None = None,
            description: str | None = None,
            node_type: Literal["Fact", "Entity", "Collection", "User", "Project"] = "Fact",
            owner_id: str = "default",
            shared_with_ids: list[str] | None = None,
            collection_id: str | None = None,
            metadata: dict | None = None,
            status: str | None = None,
            ttl_days: float | None = None,
            entity_type: str | None = None,
            auto_link: bool = False,
            semantic_threshold: float | None = None,
            links: list[dict] | None = None,
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
                status=status,
                ttl_days=ttl_days,
                entity_type=entity_type,
                auto_link=auto_link,
                semantic_threshold=semantic_threshold,
                links=links,
            )

        @mcp.tool(
            title="Get node (extended)",
            description="Retrieve a node by ID with extended fields (description, shared_with_ids).",
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def get_node(node_id: str, owner_id: str = "default") -> dict:
            return mcp_handlers_nodes.get_node(db, node_id=node_id, owner_id=owner_id)

        @mcp.tool(
            title="Update node (extended)",
            description=(
                "Update a node with extended fields support. "
                "You can update text, description, shared_with_ids, metadata, status, or ttl_days."
            ),
        )
        def update_node_ext(
            node_id: str,
            owner_id: str = "default",
            text: str | None = None,
            description: str | None = None,
            shared_with_ids: list[str] | None = None,
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
                description=description,
                shared_with_ids=shared_with_ids,
                metadata=metadata,
                status=status,
                ttl_days=ttl_days,
                entity_type=entity_type,
                versioning=versioning,
            )

        @mcp.tool(
            title="Delete node",
            description=(
                "PERMANENT: Irreversibly delete a node and all its relations. "
                "This operation cannot be undone. "
                "For reversible removal of Facts, use mark_outdated instead."
            ),
        )
        def delete_node(node_id: str, owner_id: str = "default") -> dict:
            return mcp_handlers_nodes.delete_node(
                db, node_id=node_id, owner_id=owner_id
            )

        exposed["create_node_ext"] = create_node_ext
        exposed["get_node"] = get_node
        exposed["update_node_ext"] = update_node_ext
        exposed["delete_node"] = delete_node
        return exposed

    def _register_fact_tools(self) -> Dict[str, Any]:
        """Register fact tools (search, mark_outdated, etc.)."""
        exposed: Dict[str, Any] = {}
        db = self.db_client
        config = self.config
        mcp = self.mcp
        assert mcp is not None

        @mcp.tool(
            title="Search",
            description=(
                "Semantic search using embedding similarity (cosine distance). "
                "Returns active durable nodes by default. "
                "Facts with ttl_days are omitted until include_ttl=true "
                "(still-living temporary facts only). "
                "use include_outdated=true to include outdated and archived nodes. "
                "Results ranked by similarity to query text. "
                "Supports multi-tenant isolation via owner_id. "
                "search_type: pre_filter or post_filter (see server SEARCH_TYPE default). "
                "Always includes suggested_next / do_not. Set compact=true for snippets."
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
            include_ttl: bool = False,
            search_type: str | None = None,
            compact: bool = False,
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
                include_ttl=include_ttl,
                search_type=search_type,
                compact=compact,
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
        exposed["mark_outdated"] = mark_outdated
        exposed["get_node_change_history"] = get_node_change_history

        return exposed

    def _register_triplet_tools(self) -> Dict[str, Any]:
        exposed: Dict[str, Any] = {}
        db = self.db_client
        config = self.config
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
                config=config,
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
                "Uses MERGE — same from_id, to_id, and relation_type will not create duplicates. "
                "Default: RELATED_TO for general links, MENTIONS when one node refers to another. "
                "Use SUMMARIZES, FOLLOWS_FROM, CONTRADICTS only when semantics matter. "
                "Types must be in server RELATION_ALLOWED_TYPES (see memory policies)."
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
                config=config,
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
                "Depth defaults to config (SUBGRAPH_DEFAULT_DEPTH, default 1). "
                "The node budget is filled with CONTRADICTS and FOLLOWS_FROM before MENTIONS."
            ),
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def get_context(
            node_id: str,
            owner_id: str = "default",
            depth: int | None = None,
            max_nodes: int | None = None,
            offset: int = 0,
            include_ttl: bool = False,
            relation_priority: list[str] | None = None,
            exclude_relation_types: list[str] | None = None,
        ) -> dict:
            return mcp_handlers_graph.get_context(
                db,
                config,
                node_id=node_id,
                owner_id=owner_id,
                depth=depth,
                max_nodes=max_nodes,
                offset=offset,
                include_ttl=include_ttl,
                relation_priority=relation_priority,
                exclude_relation_types=exclude_relation_types,
            )

        @mcp.tool(
            title="Recall context",
            description=(
                "Optional shortcut: semantic search + graph expansion in one call. "
                "Default recall is search → get_context → get_trace (see memory policies). "
                "Use on small/sparse graphs; prefer depth=1, include_paths=false when unsure. "
                "Always includes suggested_next / do_not. Set compact=true for snippets."
            ),
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        def recall_context(
            query: str,
            owner_id: str = "default",
            depth: int | None = None,
            limit: int | None = None,
            max_nodes: int | None = None,
            similarity_threshold: float | None = None,
            include_outdated: bool = False,
            include_ttl: bool = False,
            search_type: str | None = None,
            include_paths: bool = True,
            compact: bool = False,
            relation_priority: list[str] | None = None,
            exclude_relation_types: list[str] | None = None,
        ) -> dict:
            return mcp_handlers_graph.recall_context(
                db,
                config,
                query=query,
                owner_id=owner_id,
                depth=depth,
                limit=limit,
                max_nodes=max_nodes,
                similarity_threshold=similarity_threshold,
                include_outdated=include_outdated,
                include_ttl=include_ttl,
                search_type=search_type,
                include_paths=include_paths,
                compact=compact,
                relation_priority=relation_priority,
                exclude_relation_types=exclude_relation_types,
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
        exposed["recall_context"] = recall_context
        exposed["find_similar"] = find_similar
        exposed["create_summary_fact"] = create_summary_fact

        return exposed
