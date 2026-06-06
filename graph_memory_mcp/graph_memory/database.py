"""
FalkorDB client wrapper using official falkordb-py library.

This is a thin wrapper that provides:
- Connection management
- Access to graph instance
- Utility methods
- Embedding service integration
"""

import logging
import time
from typing import Any, Dict, List

import redis
from falkordb import FalkorDB

from graph_memory_mcp.graph_memory.cache import CacheManager

logger = logging.getLogger(__name__)


class FalkorDBClient:
    """Thin wrapper around official FalkorDB client."""

    def __init__(self, config):
        """Initialize FalkorDB client with caching."""
        self.config = config
        self.db = FalkorDB(
            host=config.falkordb_host,
            port=config.falkordb_port,
            password=config.falkordb_password,
        )
        self.graph = self.db.select_graph(config.falkordb_graph)
        self._embedding_service: Any | None = None
        self.start_time = time.time()  # Retain start_time for health check
        self.cache = CacheManager(config)

        logger.info(
            "FalkorDB client initialized (host=%s, port=%s, graph=%s)",
            self.config.falkordb_host,
            self.config.falkordb_port,
            self.config.falkordb_graph,
        )

    @property
    def redis_client(self) -> redis.Redis | None:
        """Underlying Redis connection (used for distributed job locks)."""
        return getattr(self.db, "connection", None)

    def set_embedding_service(self, service: Any) -> None:
        """Attach embedding service instance."""
        self._embedding_service = service
        logger.info(
            "Embedding service attached (dimension=%s)",
            getattr(service, "dimension", 0),
        )

    def connect(self) -> bool:
        """Test connection to FalkorDB."""
        try:
            result = self.graph.query("RETURN 1")
            return result is not None
        except Exception as e:
            logger.error("Failed to connect to FalkorDB: %s", e)
            return False

    def health_check(self) -> Dict[str, Any]:
        """Health check for FalkorDB connectivity."""
        try:
            self.graph.query("RETURN 1")
            uptime = time.time() - self.start_time

            return {
                "status": "healthy",
                "falkordb_connected": True,
                "version": "2.0.0",
                "uptime": uptime,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "falkordb_connected": False,
                "error": str(e),
            }

    def get_embedding(self, text: str) -> List[float]:
        """Get embedding from service."""
        if self._embedding_service is None:
            logger.warning("Embedding service not available")
            return []
        try:
            return self._embedding_service.get_embedding(text)
        except Exception as e:
            logger.error("Failed to get embedding: %s", e)
            return []

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings for batch of texts."""
        if self._embedding_service is None:
            logger.warning("Embedding service not available")
            return [[] for _ in texts]
        try:
            return self._embedding_service.get_embeddings_batch(texts)
        except Exception as e:
            logger.error("Failed to get batch embeddings: %s", e)
            return [[] for _ in texts]

    # ====================
    # Index Management
    # ====================

    def create_vector_index(
        self, dimension: int = 768, similarity_function: str = "cosine"
    ) -> bool:
        """Create vector index for Fact nodes."""
        try:
            query = f"""
            CREATE VECTOR INDEX FOR (n:Fact) ON (n.embedding)
            OPTIONS {{dimension: {dimension}, similarityFunction: '{similarity_function}'}}
            """
            self.graph.query(query)
            logger.info("Created vector index for Fact (dimension=%s)", dimension)
            return True
        except Exception as e:
            logger.error("Failed to create Fact vector index: %s", e)
            return False

    def create_entity_vector_index(
        self, dimension: int = 768, similarity_function: str = "cosine"
    ) -> bool:
        """Create vector index for Entity nodes."""
        try:
            query = f"""
            CREATE VECTOR INDEX FOR (n:Entity) ON (n.embedding)
            OPTIONS {{dimension: {dimension}, similarityFunction: '{similarity_function}'}}
            """
            self.graph.query(query)
            logger.info("Created vector index for Entity (dimension=%s)", dimension)
            return True
        except Exception as e:
            logger.error("Failed to create Entity vector index: %s", e)
            return False

    def ensure_vector_indexes_if_missing(
        self,
        *,
        dimension: int | None = None,
        similarity_function: str = "cosine",
    ) -> Dict[str, bool]:
        """Create Fact/Entity vector indexes when absent (idempotent)."""
        dim = int(dimension or getattr(self._embedding_service, "dimension", 0) or 0)
        if dim <= 0:
            logger.warning(
                "Cannot ensure vector indexes: embedding dimension is %s", dim
            )
            return self.get_vector_index_status()

        status = self.get_vector_index_status()
        if not status.get("Fact"):
            self.create_vector_index(
                dimension=dim, similarity_function=similarity_function
            )
        if not status.get("Entity"):
            self.create_entity_vector_index(
                dimension=dim, similarity_function=similarity_function
            )
        return self.get_vector_index_status()

    def create_owner_id_range_index(self, label: str) -> bool:
        """Create range index on owner_id for faster tenant-scoped MATCH."""
        try:
            query = f"CREATE RANGE INDEX FOR (n:{label}) ON (n.owner_id)"
            self.graph.query(query)
            logger.info("Created range index for %s.owner_id", label)
            return True
        except Exception as e:
            if (
                "already indexed" in str(e).lower()
                or "already exists" in str(e).lower()
            ):
                return True
            logger.error("Failed to create %s owner_id range index: %s", label, e)
            return False

    def get_owner_id_range_index_status(self) -> Dict[str, bool]:
        """Return whether Fact/Entity owner_id range indexes exist."""
        status = {"Fact": False, "Entity": False}
        try:
            result = self.graph.query("CALL db.indexes()")
            if not result or not hasattr(result, "result_set"):
                return status
            for row in result.result_set:
                if len(row) < 3:
                    continue
                label = str(row[0]) if row[0] else ""
                prop = str(row[1]) if row[1] else ""
                idx_type = str(row[2]) if row[2] else ""
                if prop != "owner_id" or "range" not in idx_type.lower():
                    continue
                if "Fact" in label:
                    status["Fact"] = True
                if "Entity" in label:
                    status["Entity"] = True
        except Exception as e:
            logger.error("Failed to get owner_id range index status: %s", e)
        return status

    def ensure_owner_id_range_indexes_if_missing(self) -> Dict[str, bool]:
        """Create Fact/Entity owner_id range indexes when absent (idempotent)."""
        status = self.get_owner_id_range_index_status()
        if not status.get("Fact"):
            self.create_owner_id_range_index("Fact")
        if not status.get("Entity"):
            self.create_owner_id_range_index("Entity")
        return self.get_owner_id_range_index_status()

    def ensure_search_indexes_if_missing(
        self,
        *,
        dimension: int | None = None,
        similarity_function: str = "cosine",
    ) -> Dict[str, Any]:
        """Ensure indexes used by owner-scoped semantic search."""
        vector_status = self.ensure_vector_indexes_if_missing(
            dimension=dimension,
            similarity_function=similarity_function,
        )
        range_status = self.ensure_owner_id_range_indexes_if_missing()
        return {"vector": vector_status, "owner_id_range": range_status}

    def get_vector_index_status(self) -> Dict[str, Any]:
        """Get vector index status for Fact and Entity."""
        try:
            query = "CALL db.indexes()"
            result = self.graph.query(query)

            status = {"Fact": False, "Entity": False}

            if result and hasattr(result, "result_set"):
                for row in result.result_set:
                    # Row format: [label, property, type, ...]
                    if len(row) >= 3:
                        label = str(row[0]) if row[0] else ""
                        prop = str(row[1]) if row[1] else ""
                        idx_type = str(row[2]) if row[2] else ""

                        if (
                            "Fact" in label
                            and "embedding" in prop
                            and "vector" in idx_type.lower()
                        ):
                            status["Fact"] = True
                        if (
                            "Entity" in label
                            and "embedding" in prop
                            and "vector" in idx_type.lower()
                        ):
                            status["Entity"] = True

            return status
        except Exception as e:
            logger.error("Failed to get vector index status: %s", e)
            return {"Fact": False, "Entity": False}
