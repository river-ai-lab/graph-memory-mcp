"""
FalkorDB client wrapper using official falkordb-py library.

Storage layout: **graph-per-owner**. Every owner_id lives in its own FalkorDB
graph (`{FALKORDB_GRAPH}_{owner_id}`), so vector/range indexes are private to
the owner: no ANN dilution by other tenants, owner scans touch only the
owner's nodes, and isolation is physical. Queries are routed by the
`owner_id` entry of query params.
"""

import logging
import time
from typing import Any, Dict, List, Optional

import redis
from falkordb import FalkorDB

from graph_memory_mcp import __version__
from graph_memory_mcp.graph_memory.cache import CacheManager
from graph_memory_mcp.graph_memory.utils import new_uid

logger = logging.getLogger(__name__)


class FalkorDBClient:
    """Thin wrapper around official FalkorDB client with owner-graph routing."""

    def __init__(self, config):
        """Initialize FalkorDB client with caching."""
        self.config = config
        self.db = FalkorDB(
            host=config.falkordb_host,
            port=config.falkordb_port,
            password=config.falkordb_password,
        )
        # Base graph: connectivity checks only; data lives in per-owner graphs.
        self.graph = self.db.select_graph(config.falkordb_graph)
        self._graphs: Dict[str, Any] = {}
        self._search_indexes_ready: set[str] = set()
        self._embedding_service: Any | None = None
        self.start_time = time.time()  # Retain start_time for health check
        self.cache = CacheManager(config)

        logger.info(
            "FalkorDB client initialized (host=%s, port=%s, graph prefix=%s, "
            "layout=graph-per-owner)",
            self.config.falkordb_host,
            self.config.falkordb_port,
            self.config.falkordb_graph,
        )

    # ====================
    # Owner-graph routing
    # ====================

    def graph_name(self, owner_id: str) -> str:
        return f"{self.config.falkordb_graph}_{owner_id}"

    def graph_for(self, owner_id: str):
        """Graph instance for an owner (created lazily by FalkorDB on write)."""
        name = self.graph_name(owner_id)
        graph = self._graphs.get(name)
        if graph is None:
            graph = self.db.select_graph(name)
            self._graphs[name] = graph
        return graph

    def query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        owner_id: Optional[str] = None,
    ) -> Any:
        """Execute a query on the owner's graph.

        The owner is taken from `owner_id` or from `params["owner_id"]` —
        every data query carries it. Falls back to the base graph.
        """
        owner = owner_id or (params or {}).get("owner_id")
        graph = self.graph_for(str(owner)) if owner else self.graph
        return graph.query(query, params=params)

    def list_owners(self) -> List[str]:
        """Owners discovered from existing per-owner graphs (GRAPH.LIST)."""
        prefix = f"{self.config.falkordb_graph}_"
        owners: List[str] = []
        try:
            client = self.redis_client
            if client is None:
                return owners
            for name in client.execute_command("GRAPH.LIST") or []:
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace")
                name = str(name)
                if name.startswith(prefix):
                    owners.append(name[len(prefix) :])
        except Exception as exc:  # noqa: BLE001
            logger.warning("GRAPH.LIST failed: %s", exc)
        return sorted(set(owners))

    def delete_owner_graph(self, owner_id: str) -> bool:
        """Irreversibly delete an owner's graph (all nodes, edges, indexes)."""
        name = self.graph_name(owner_id)
        try:
            self.graph_for(owner_id).delete()
        except Exception as exc:  # noqa: BLE001
            if "empty key" not in str(exc).lower():
                logger.error("Failed to delete graph %s: %s", name, exc)
                return False
        self._graphs.pop(name, None)
        self._search_indexes_ready.discard(name)
        logger.info("Deleted owner graph %s", name)
        return True

    def prune_empty_owner_graphs(self) -> List[str]:
        """Delete owner graphs that contain zero nodes (test/deleted leftovers)."""
        pruned: List[str] = []
        for owner_id in self.list_owners():
            try:
                result = self.graph_for(owner_id).query("MATCH (n) RETURN count(n)")
                count = int(result.result_set[0][0]) if result.result_set else 0
            except Exception as exc:  # noqa: BLE001
                logger.warning("Prune: failed to count %s: %s", owner_id, exc)
                continue
            if count == 0 and self.delete_owner_graph(owner_id):
                pruned.append(owner_id)
        return pruned

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
                "version": __version__,
                "uptime": uptime,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "falkordb_connected": False,
                "error": str(e),
            }

    def get_embedding(self, text: str, kind: str = "passage") -> List[float]:
        """Get embedding from service (with config-driven LRU cache)."""
        if self._embedding_service is None:
            logger.warning("Embedding service not available")
            return []
        cache_key = f"{kind}:{text}"
        cached = self.cache.get_embedding(cache_key)
        if cached is not None:
            return cached
        try:
            embedding = self._embedding_service.get_embedding(text, kind=kind)
        except TypeError:
            # Custom embedding services may not accept `kind`.
            embedding = self._embedding_service.get_embedding(text)
        except Exception as e:
            logger.error("Failed to get embedding: %s", e)
            return []
        if embedding:
            self.cache.set_embedding(cache_key, embedding)
        return embedding

    def get_embeddings_batch(
        self, texts: List[str], kind: str = "passage"
    ) -> List[List[float]]:
        """Get embeddings for batch of texts."""
        if self._embedding_service is None:
            logger.warning("Embedding service not available")
            return [[] for _ in texts]
        try:
            return self._embedding_service.get_embeddings_batch(texts, kind=kind)
        except TypeError:
            return self._embedding_service.get_embeddings_batch(texts)
        except Exception as e:
            logger.error("Failed to get batch embeddings: %s", e)
            return [[] for _ in texts]

    # ====================
    # Index Management (per owner graph)
    # ====================

    def create_vector_index(
        self,
        dimension: int = 768,
        similarity_function: str = "cosine",
        owner_id: str = "default",
    ) -> bool:
        """Create vector index for Fact nodes in the owner's graph."""
        return self._create_vector_index(
            "Fact", dimension, similarity_function, owner_id
        )

    def create_entity_vector_index(
        self,
        dimension: int = 768,
        similarity_function: str = "cosine",
        owner_id: str = "default",
    ) -> bool:
        """Create vector index for Entity nodes in the owner's graph."""
        return self._create_vector_index(
            "Entity", dimension, similarity_function, owner_id
        )

    def _create_vector_index(
        self, label: str, dimension: int, similarity_function: str, owner_id: str
    ) -> bool:
        try:
            query = f"""
            CREATE VECTOR INDEX FOR (n:{label}) ON (n.embedding)
            OPTIONS {{dimension: {int(dimension)}, similarityFunction: '{similarity_function}'}}
            """
            self.graph_for(owner_id).query(query)
            logger.info(
                "Created vector index for %s (dimension=%s, owner=%s)",
                label,
                dimension,
                owner_id,
            )
            return True
        except Exception as e:
            if "already indexed" in str(e).lower():
                return True
            logger.error("Failed to create %s vector index: %s", label, e)
            return False

    def _create_range_index(self, label: str, prop: str, owner_id: str) -> bool:
        try:
            # FalkorDB syntax: CREATE INDEX (the RANGE keyword is not accepted).
            query = f"CREATE INDEX FOR (n:{label}) ON (n.{prop})"
            self.graph_for(owner_id).query(query)
            return True
        except Exception as e:
            if (
                "already indexed" in str(e).lower()
                or "already exists" in str(e).lower()
            ):
                return True
            logger.error("Failed to create %s %s range index: %s", label, prop, e)
            return False

    def ensure_search_indexes_if_missing(
        self,
        *,
        owner_id: str = "default",
        dimension: int | None = None,
        similarity_function: str = "cosine",
    ) -> Dict[str, Any]:
        """Ensure indexes used by semantic search in the owner's graph (memoized)."""
        graph_name = self.graph_name(owner_id)
        if graph_name in self._search_indexes_ready:
            return {"vector": {"Fact": True, "Entity": True}}

        vector_status = self.ensure_vector_indexes_if_missing(
            owner_id=owner_id,
            dimension=dimension,
            similarity_function=similarity_function,
        )
        range_ok = all(
            self._create_range_index(label, prop, owner_id)
            for label in ("Fact", "Entity")
            for prop in ("uid", "owner_id", "project")
        )
        if range_ok and all(vector_status.values()):
            self._search_indexes_ready.add(graph_name)
        return {"vector": vector_status}

    def ensure_vector_indexes_if_missing(
        self,
        *,
        owner_id: str = "default",
        dimension: int | None = None,
        similarity_function: str = "cosine",
    ) -> Dict[str, bool]:
        """Create Fact/Entity vector indexes when absent (idempotent)."""
        dim = int(dimension or getattr(self._embedding_service, "dimension", 0) or 0)
        if dim <= 0:
            logger.warning(
                "Cannot ensure vector indexes: embedding dimension is %s", dim
            )
            return self.get_vector_index_status(owner_id=owner_id)

        status = self.get_vector_index_status(owner_id=owner_id)
        if not status.get("Fact"):
            self.create_vector_index(
                dimension=dim,
                similarity_function=similarity_function,
                owner_id=owner_id,
            )
        if not status.get("Entity"):
            self.create_entity_vector_index(
                dimension=dim,
                similarity_function=similarity_function,
                owner_id=owner_id,
            )
        return self.get_vector_index_status(owner_id=owner_id)

    def _indexed_props_by_label(
        self, owner_id: str, wanted_type: str
    ) -> Dict[str, set]:
        """Map label -> set of properties covered by an index of wanted_type."""
        # db.indexes() row: [label, [props...], {prop: [types...]}, ...]
        out: Dict[str, set] = {}
        result = self.graph_for(owner_id).query("CALL db.indexes()")
        if not result or not hasattr(result, "result_set"):
            return out
        for row in result.result_set:
            if len(row) < 3:
                continue
            label = str(row[0]) if row[0] else ""
            types_by_prop = row[2] if isinstance(row[2], dict) else {}
            props = {
                str(prop)
                for prop, types in types_by_prop.items()
                if any(wanted_type in str(t).lower() for t in (types or []))
            }
            if props:
                out.setdefault(label, set()).update(props)
        return out

    def get_vector_index_status(self, owner_id: str = "default") -> Dict[str, Any]:
        """Get vector index status for Fact and Entity in the owner's graph."""
        status = {"Fact": False, "Entity": False}
        try:
            indexed = self._indexed_props_by_label(owner_id, "vector")
            for label in status:
                status[label] = "embedding" in indexed.get(label, set())
        except Exception as e:
            logger.error("Failed to get vector index status: %s", e)
        return status

    # ====================
    # Startup backfills (legacy data, idempotent)
    # ====================

    def backfill_all_owners(self) -> None:
        """Run legacy backfills (uid, Entity name_norm) on every owner graph."""
        for owner_id in self.list_owners():
            try:
                self.backfill_uids(owner_id=owner_id)
                self.backfill_entity_name_norm(owner_id=owner_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Backfill failed for owner %s: %s", owner_id, exc)

    def backfill_entity_name_norm(self, owner_id: str = "default") -> None:
        """Assign name_norm to legacy Entity nodes (idempotent, single query)."""
        try:
            self.graph_for(owner_id).query("""
                MATCH (n:Entity)
                WHERE n.name_norm IS NULL AND n.text IS NOT NULL
                SET n.name_norm = toLower(trim(n.text))
                """)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Entity name_norm backfill failed: %s", exc)

    def backfill_uids(self, batch_size: int = 1000, owner_id: str = "default") -> int:
        """Assign uid to legacy nodes created before stable ids (idempotent)."""
        graph = self.graph_for(owner_id)
        total = 0
        while True:
            result = graph.query(
                f"MATCH (n) WHERE n.uid IS NULL RETURN id(n) LIMIT {int(batch_size)}"
            )
            rows = getattr(result, "result_set", None) or []
            if not rows:
                break
            pairs = [[int(row[0]), new_uid()] for row in rows]
            graph.query(
                """
                UNWIND $pairs AS p
                MATCH (n) WHERE id(n) = p[0]
                SET n.uid = p[1]
                """,
                params={"pairs": pairs},
            )
            total += len(pairs)
            if len(rows) < batch_size:
                break
        if total:
            logger.info(
                "Backfilled uid for %d legacy nodes (owner=%s)", total, owner_id
            )
        return total
