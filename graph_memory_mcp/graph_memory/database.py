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
from typing import Any, Dict, List, Optional

import redis
from falkordb import FalkorDB
from sentence_transformers import SentenceTransformer

from graph_memory_mcp.graph_memory.cache import CacheManager
from graph_memory_mcp.graph_memory.utils import (
    dump_json,
    ensure_text,
    escape_value,
    format_vecf32,
    load_json,
    normalize_owner_id,
    parse_embedding_value,
)

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
        self.embedder = SentenceTransformer(config.embedding_model)
        self.start_time = time.time()  # Retain start_time for health check
        self.cache = CacheManager(config)

        logger.info(
            "FalkorDB client initialized (host=%s, port=%s, graph=%s)",
            self.config.falkordb_host,
            self.config.falkordb_port,
            self.config.falkordb_graph,
        )

    def get_embedding(self, text: str) -> List[float]:
        """Get embedding for text with caching."""
        if cached := self.cache.get_embedding(text):
            return cached
        embedding = self.embedder.encode(text).tolist()
        self.cache.set_embedding(text, embedding)
        return embedding

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

    # ====================
    # Utility Methods
    # ====================

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
