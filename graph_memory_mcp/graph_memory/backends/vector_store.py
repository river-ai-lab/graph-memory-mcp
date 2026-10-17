"""Vector store protocol for semantic search.

Separates vector operations from graph storage, allowing future Qdrant/Milvus/etc.
implementations without touching handlers.
"""

from __future__ import annotations

from typing import Any, Protocol


class VectorStore(Protocol):
    """Vector search operations independent of graph backend.
    
    ArcadeDB implements this inline (embedding is a vertex property, HNSW index
    per database). A future Qdrant implementation would use external storage.
    """

    def ensure_vector_index(
        self,
        collection: str,
        dimension: int,
        *,
        similarity: str = "cosine",
    ) -> None:
        """Create or verify a vector index for the given collection/label.
        
        Args:
            collection: Node type (Fact, Entity) or external collection name
            dimension: Embedding dimension
            similarity: Distance metric (cosine, euclidean, dot)
        """
        ...

    def vector_search(
        self,
        collection: str,
        embedding: list[float],
        *,
        limit: int,
        max_distance: float,
        filter_rids: list[str] | None = None,
        acl_tokens: list[str] | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Find nearest neighbors by embedding similarity.
        
        Filter-first: if filter_rids or acl_tokens provided, apply server-side
        pre-filtering before ANN search (ArcadeDB subquery, Qdrant payload filter).
        
        Args:
            collection: Node type to search
            embedding: Query vector
            limit: Max results
            max_distance: Cosine distance threshold (0-2)
            filter_rids: Pre-computed record IDs (ArcadeDB)
            acl_tokens: ACL tokens for access control (shared-graph only)
            metadata_filter: Additional attribute filters
            
        Returns:
            List of dicts with keys: uid, node_type, text, status, created_at,
            metadata_str, distance
        """
        ...

    def get_vector(self, collection: str, node_id: str) -> tuple[bool, Any]:
        """Retrieve embedding for a node.
        
        Returns:
            (exists, embedding) tuple
        """
        ...

    def set_vector(
        self,
        collection: str,
        node_id: str,
        embedding: list[float],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store or update an embedding.
        
        Args:
            collection: Node type
            node_id: Unique node identifier
            embedding: Vector to store
            metadata: Additional payload (for Qdrant filters, unused in ArcadeDB)
        """
        ...

    def delete_vector(self, collection: str, node_id: str) -> None:
        """Remove an embedding (when node is deleted)."""
        ...


class ArcadeVectorStore:
    """VectorStore implementation using ArcadeDB's inline HNSW indexes.
    
    This is a thin adapter: ArcadeDB stores embeddings as vertex properties,
    so most operations are handled by the graph backend. Kept here for the
    protocol contract and future Qdrant migration.
    """

    def __init__(self, arcade_client: Any):
        self.client = arcade_client

    def ensure_vector_index(
        self,
        collection: str,
        dimension: int,
        *,
        similarity: str = "cosine",
    ) -> None:
        """Delegate to ArcadeDB ensure_vector_index."""
        self.client.ensure_vector_index(collection, dimension)

    def vector_search(
        self,
        collection: str,
        embedding: list[float],
        *,
        limit: int,
        max_distance: float,
        filter_rids: list[str] | None = None,
        acl_tokens: list[str] | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """ArcadeDB filter-first vector search via arcade_search.neighbor_rows."""
        from graph_memory_mcp.graph_memory.backends.arcade_search import neighbor_rows

        # Use the current owner_id from arcade's owner_scope
        owner_id = self.client.owner_literal(
            getattr(self.client, "_current_owner", "default")
        )
        
        rows = neighbor_rows(
            self.client,
            node_type=collection,
            embedding=embedding,
            owner_id=owner_id,
            limit=limit,
            max_distance=max_distance,
            acl_tokens=acl_tokens,
            include_outdated=False,
        )
        
        # Convert row format to dict
        return [
            {
                "uid": row[0],
                "node_type": row[1],
                "text": row[2],
                "status": row[3],
                "created_at": row[4],
                "metadata_str": row[5],
                "distance": row[6],
            }
            for row in rows
        ]

    def get_vector(self, collection: str, node_id: str) -> tuple[bool, Any]:
        """ArcadeDB stores embeddings as vertex properties; delegate to backend."""
        owner_id = getattr(self.client, "_current_owner", "default")
        return self.client.fact_embedding(node_id, owner_id)

    def set_vector(
        self,
        collection: str,
        node_id: str,
        embedding: list[float],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """ArcadeDB embeddings are set during vertex creation/update; no-op."""
        pass

    def delete_vector(self, collection: str, node_id: str) -> None:
        """ArcadeDB embeddings are deleted with the vertex; no-op."""
        pass
