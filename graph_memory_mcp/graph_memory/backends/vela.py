"""Vela graph adapter.

Vela is the Vela-Engineering fork of Kuzu (embedded, disk-native). The Python
API is the ``kuzu`` module shipped on that repo's GitHub releases, not the
archived PyPI package. ``kuzu.Database`` takes a file path; each owner is one
file under ``VELA_PATH``.

Only this package imports ``kuzu``. Callers use the same operations as the
Falkor adapter.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from graph_memory_mcp import __version__
from graph_memory_mcp.graph_memory.backends.vela_ops import (
    NODE_LABELS,
    VelaOps,
    ident,
    node_label,
)
from graph_memory_mcp.graph_memory.cache import CacheManager

logger = logging.getLogger(__name__)

_FLOAT_DIM = re.compile(r"FLOAT\[(\d+)\]", re.IGNORECASE)

_NODE_COLUMNS = """
    uid STRING,
    owner_id STRING,
    text STRING,
    description STRING,
    status STRING,
    created_at INT64,
    updated_at INT64,
    metadata_str STRING,
    tags STRING[],
    meta_type STRING,
    confidence DOUBLE,
    project STRING,
    created_by STRING,
    shared_with_ids STRING[],
    ttl_days DOUBLE,
    expires_at INT64,
    last_dedup_at INT64,
    source_str STRING,
    source_ref STRING,
    source_type STRING,
    source_uri STRING,
    content_hash STRING,
    source_updated_at INT64,
    name_norm STRING,
    type STRING,
    access_count INT64,
    last_accessed_at INT64,
    merged_into STRING,
    fact_id STRING,
    version_timestamp INT64,
    original_created_at INT64
"""


class _Result:
    def __init__(self, rows: list[list[Any]]):
        self.result_set = rows


class _Holder:
    def __init__(self, db: Any, conn: Any, path: str):
        self.db = db
        self.conn = conn
        self.path = path
        self.schema_ready = False
        self.embedding_dim: int | None = None
        self.tables: set[str] = set()
        self.rel_pairs: set[tuple[str, str, str]] = set()


def _load_kuzu():
    try:
        import kuzu
    except ImportError as exc:
        raise RuntimeError(
            "Vela backend needs the Vela Kuzu fork. Install a wheel from "
            "https://github.com/Vela-Engineering/kuzu/releases "
            "(tested: v0.12.0-vela.2efa20b). PyPI `kuzu` is the archived "
            "upstream, not this fork."
        ) from exc
    return kuzu


class VelaClient(VelaOps):
    """Embedded Vela database, one file per owner."""

    def __init__(self, config):
        self.config = config
        self._kuzu = _load_kuzu()
        root = str(getattr(config, "vela_path", None) or "data/vela")
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        graph = str(getattr(config, "vela_graph", None) or "memory")
        self.graph_prefix = ident(re.sub(r"[^A-Za-z0-9_]", "_", graph) or "memory")
        self._owners: dict[str, _Holder] = {}
        self._system: _Holder | None = None
        self._search_indexes_ready: set[str] = set()
        self._embedding_service: Any | None = None
        self.start_time = time.time()
        self.cache = CacheManager(config)
        logger.info(
            "Vela client initialized (path=%s, graph prefix=%s, layout=file-per-owner)",
            self.root,
            self.graph_prefix,
        )

    def _owner_path(self, owner_id: str) -> str:
        owner = str(owner_id)
        if owner in {"", ".", ".."} or "/" in owner or "\\" in owner:
            raise ValueError(f"Invalid owner_id for a database file: {owner!r}")
        return os.path.join(self.root, f"{self.graph_prefix}_{owner}")

    def _open_file(self, path: str) -> _Holder:
        db = self._kuzu.Database(path)
        conn = self._kuzu.Connection(db)
        return _Holder(db, conn, path)

    def _close_holder(self, holder: _Holder | None) -> None:
        if holder is None:
            return
        for obj in (holder.conn, holder.db):
            close = getattr(obj, "close", None)
            if close is None:
                continue
            try:
                close()
            except Exception:  # noqa: BLE001
                logger.debug("Vela close failed for %s", holder.path, exc_info=True)

    def connection_for(self, owner_id: str) -> _Holder:
        owner = str(owner_id)
        holder = self._owners.get(owner)
        if holder is None:
            holder = self._open_file(self._owner_path(owner))
            self._owners[owner] = holder
        return holder

    def _system_holder(self) -> _Holder:
        if self._system is None:
            self._system = self._open_file(os.path.join(self.root, "_system"))
        return self._system

    def _refresh_tables(self, holder: _Holder) -> None:
        rows = holder.conn.execute("CALL SHOW_TABLES() RETURN *").get_all()
        holder.tables = {str(row[1]) for row in rows}

    def _column_type(self, holder: _Holder, table: str, column: str) -> str | None:
        rows = holder.conn.execute(f"CALL TABLE_INFO('{ident(table)}') RETURN *").get_all()
        for row in rows:
            if str(row[1]) == column:
                return str(row[2])
        return None

    def _read_dim(self, holder: _Holder) -> int | None:
        if "_VelaMeta" not in holder.tables:
            return None
        rows = holder.conn.execute(
            "MATCH (m:_VelaMeta) WHERE m.key = 'embedding_dim' RETURN m.value"
        ).get_all()
        if not rows or rows[0][0] is None:
            return None
        return int(rows[0][0])

    def ensure_schema(self, owner_id: str) -> _Holder:
        holder = self.connection_for(owner_id)
        if holder.schema_ready:
            return holder
        self._refresh_tables(holder)
        for label in NODE_LABELS:
            if label not in holder.tables:
                holder.conn.execute(
                    f"CREATE NODE TABLE {label}({_NODE_COLUMNS}, PRIMARY KEY (uid))"
                )
        self._refresh_tables(holder)
        if "_VelaMeta" not in holder.tables:
            holder.conn.execute(
                "CREATE NODE TABLE _VelaMeta(key STRING, value INT64, PRIMARY KEY (key))"
            )
            self._refresh_tables(holder)
        holder.embedding_dim = self._read_dim(holder)
        if holder.embedding_dim is None:
            col_type = self._column_type(holder, "Fact", "embedding")
            match = _FLOAT_DIM.search(col_type or "")
            if match:
                holder.embedding_dim = int(match.group(1))
        holder.schema_ready = True
        return holder

    def embedding_ready(self, owner_id: str) -> bool:
        holder = self.ensure_schema(owner_id)
        return bool(holder.embedding_dim)

    def ensure_embedding(self, owner_id: str, dimension: int) -> None:
        dim = int(dimension)
        if dim <= 0:
            raise ValueError(f"Embedding dimension must be positive, got {dim}")
        holder = self.ensure_schema(owner_id)
        if holder.embedding_dim == dim:
            return
        if holder.embedding_dim not in (None, 0):
            raise ValueError(
                f"Vela embedding dimension is {holder.embedding_dim}, not {dim}. "
                "Changing model dimension needs a new database directory."
            )
        for label in ("Fact", "Entity", "Collection"):
            existing = self._column_type(holder, label, "embedding")
            if existing:
                match = _FLOAT_DIM.search(existing)
                if match and int(match.group(1)) != dim:
                    raise ValueError(
                        f"{label}.embedding is {existing}, expected FLOAT[{dim}]"
                    )
                continue
            holder.conn.execute(f"ALTER TABLE {label} ADD embedding FLOAT[{dim}]")
        holder.conn.execute(
            """
            MERGE (m:_VelaMeta {key: 'embedding_dim'})
            ON CREATE SET m.value = $dim
            ON MATCH SET m.value = $dim
            """,
            {"dim": dim},
        )
        holder.embedding_dim = dim

    def ensure_rel(self, owner_id: str, rel_type: str, src: str, dst: str) -> None:
        rel = ident(rel_type)
        src_label = node_label(src)
        dst_label = node_label(dst)
        holder = self.ensure_schema(owner_id)
        pair = (rel, src_label, dst_label)
        if pair in holder.rel_pairs:
            return
        self._refresh_tables(holder)
        if rel not in holder.tables:
            holder.conn.execute(
                f"""
                CREATE REL TABLE {rel}(
                    FROM {src_label} TO {dst_label},
                    created_at INT64,
                    auto_linked BOOL,
                    props STRING
                )
                """
            )
            holder.tables.add(rel)
        else:
            try:
                holder.conn.execute(
                    f"ALTER TABLE {rel} ADD FROM {src_label} TO {dst_label}"
                )
            except Exception as exc:  # noqa: BLE001
                message = str(exc).lower()
                if "exist" not in message and "already" not in message:
                    raise
        holder.rel_pairs.add(pair)

    def has_table(self, owner_id: str, name: str) -> bool:
        holder = self.ensure_schema(owner_id)
        self._refresh_tables(holder)
        return name in holder.tables

    def query(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        owner_id: str | None = None,
    ) -> _Result:
        bound = dict(params or {})
        owner = owner_id or bound.get("owner_id")
        if owner:
            holder = self.ensure_schema(str(owner))
            conn = holder.conn
        else:
            conn = self._system_holder().conn
        result = conn.execute(query, bound)
        if isinstance(result, list):
            result = result[0]
        return _Result(result.get_all())

    def rows(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        owner_id: str | None = None,
    ) -> list[list[Any]]:
        return self.query(query, params, owner_id=owner_id).result_set

    def list_owners(self) -> list[str]:
        prefix = f"{self.graph_prefix}_"
        owners: list[str] = []
        try:
            names = os.listdir(self.root)
        except FileNotFoundError:
            return []
        for name in names:
            path = os.path.join(self.root, name)
            if not os.path.isfile(path) or name.endswith(".wal"):
                continue
            if not name.startswith(prefix):
                continue
            owner = name[len(prefix) :]
            if owner:
                owners.append(owner)
        return sorted(set(owners))

    def delete_owner_graph(self, owner_id: str) -> bool:
        owner = str(owner_id)
        path = self._owner_path(owner)
        self._close_holder(self._owners.pop(owner, None))
        self._search_indexes_ready.discard(owner)
        removed = False
        for suffix in ("", ".wal"):
            candidate = path + suffix
            if os.path.exists(candidate):
                try:
                    os.remove(candidate)
                    removed = True
                except OSError as exc:
                    logger.error("Failed to delete %s: %s", candidate, exc)
                    return False
        if removed:
            logger.info("Deleted Vela owner database %s", path)
        return True

    def prune_empty_owner_graphs(self) -> list[str]:
        pruned: list[str] = []
        for owner_id in self.list_owners():
            try:
                rows = self.rows(
                    """
                    MATCH (n)
                    WHERE label(n) IN ['Fact', 'Entity', 'Collection', 'FactVersion']
                    RETURN count(n)
                    """,
                    owner_id=owner_id,
                )
                count = int(rows[0][0]) if rows else 0
            except Exception as exc:  # noqa: BLE001
                logger.warning("Prune: failed to count %s: %s", owner_id, exc)
                continue
            if count == 0 and self.delete_owner_graph(owner_id):
                pruned.append(owner_id)
        return pruned

    @property
    def redis_client(self) -> None:
        """Vela has no Redis lock. Jobs run without a distributed lock."""
        return None

    def set_embedding_service(self, service: Any) -> None:
        self._embedding_service = service
        logger.info(
            "Embedding service attached (dimension=%s)",
            getattr(service, "dimension", 0),
        )

    def connect(self) -> bool:
        try:
            result = self._system_holder().conn.execute("RETURN 1")
            return result is not None
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to connect to Vela: %s", exc)
            return False

    def health_check(self) -> dict[str, Any]:
        try:
            self._system_holder().conn.execute("RETURN 1")
            return {
                "status": "healthy",
                "vela_connected": True,
                "backend": "vela",
                "version": __version__,
                "uptime": time.time() - self.start_time,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "unhealthy",
                "vela_connected": False,
                "backend": "vela",
                "error": str(exc),
            }

    def get_embedding(self, text: str, kind: str = "passage") -> list[float]:
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
            embedding = self._embedding_service.get_embedding(text)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to get embedding: %s", exc)
            return []
        if embedding:
            self.cache.set_embedding(cache_key, embedding)
        return embedding

    def get_embeddings_batch(
        self, texts: list[str], kind: str = "passage"
    ) -> list[list[float]]:
        if self._embedding_service is None:
            logger.warning("Embedding service not available")
            return [[] for _ in texts]
        try:
            return self._embedding_service.get_embeddings_batch(texts, kind=kind)
        except TypeError:
            return self._embedding_service.get_embeddings_batch(texts)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to get batch embeddings: %s", exc)
            return [[] for _ in texts]

    def create_vector_index(
        self,
        dimension: int = 768,
        similarity_function: str = "cosine",
        owner_id: str = "default",
    ) -> bool:
        del similarity_function
        try:
            self.ensure_embedding(owner_id, dimension)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to prepare Fact embedding column: %s", exc)
            return False

    def create_entity_vector_index(
        self,
        dimension: int = 768,
        similarity_function: str = "cosine",
        owner_id: str = "default",
    ) -> bool:
        return self.create_vector_index(dimension, similarity_function, owner_id)

    def ensure_search_indexes_if_missing(
        self,
        *,
        owner_id: str = "default",
        dimension: int | None = None,
        similarity_function: str = "cosine",
    ) -> dict[str, Any]:
        if owner_id in self._search_indexes_ready:
            return {"vector": {"Fact": True, "Entity": True}}
        vector_status = self.ensure_vector_indexes_if_missing(
            owner_id=owner_id,
            dimension=dimension,
            similarity_function=similarity_function,
        )
        if all(vector_status.values()):
            self._search_indexes_ready.add(owner_id)
        return {"vector": vector_status}

    def ensure_vector_indexes_if_missing(
        self,
        *,
        owner_id: str = "default",
        dimension: int | None = None,
        similarity_function: str = "cosine",
    ) -> dict[str, bool]:
        del similarity_function
        dim = int(dimension or getattr(self._embedding_service, "dimension", 0) or 0)
        if dim <= 0:
            logger.warning("Cannot ensure Vela embedding column: dimension is %s", dim)
            return self.get_vector_index_status(owner_id=owner_id)
        self.ensure_embedding(owner_id, dim)
        return self.get_vector_index_status(owner_id=owner_id)

    def get_vector_index_status(self, owner_id: str = "default") -> dict[str, Any]:
        """True when the fixed-size embedding column exists.

        Search is exact cosine. This fork's vector extension is not loadable
        from the published 0.12 extension URL.
        """
        ready = self.embedding_ready(owner_id) if self._owner_file_exists(owner_id) else False
        if not self._owner_file_exists(owner_id):
            return {"Fact": False, "Entity": False}
        return {"Fact": ready, "Entity": ready}

    def _owner_file_exists(self, owner_id: str) -> bool:
        path = self._owner_path(owner_id)
        return os.path.isfile(path) or owner_id in self._owners

    def backfill_all_owners(self) -> None:
        for owner_id in self.list_owners():
            try:
                self.backfill_uids(owner_id=owner_id)
                self.backfill_entity_name_norm(owner_id=owner_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Backfill failed for owner %s: %s", owner_id, exc)

    def backfill_entity_name_norm(self, owner_id: str = "default") -> None:
        if not self._owner_file_exists(owner_id):
            return
        try:
            self.query(
                """
                MATCH (n:Entity)
                WHERE n.name_norm IS NULL AND n.text IS NOT NULL
                SET n.name_norm = lower(trim(n.text))
                """,
                owner_id=owner_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Entity name_norm backfill failed: %s", exc)

    def backfill_uids(self, batch_size: int = 1000, owner_id: str = "default") -> int:
        del batch_size, owner_id
        return 0

    def count_labeled(self, node_type: str, owner_id: str) -> int:
        from graph_memory_mcp.graph_memory.backends.vela_search import count_labeled

        return count_labeled(self, node_type, owner_id)

    def similarity_rows(self, **kwargs: Any) -> list[list[Any]]:
        from graph_memory_mcp.graph_memory.backends.vela_search import similarity_rows

        return similarity_rows(self, **kwargs)

    def ann_rows(self, **kwargs: Any) -> list[list[Any]]:
        from graph_memory_mcp.graph_memory.backends.vela_search import ann_rows

        return ann_rows(self, **kwargs)

    def fact_embedding(self, fact_id: str, owner_id: str) -> tuple[bool, Any]:
        from graph_memory_mcp.graph_memory.backends.vela_search import fact_embedding

        return fact_embedding(self, fact_id, owner_id)
