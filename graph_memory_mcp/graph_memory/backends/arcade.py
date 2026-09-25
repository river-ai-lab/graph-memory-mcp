"""ArcadeDB graph adapter.

ArcadeDB is a server: many clients share one database. Owners are not separate
databases. Each vertex type uses ``partitioned('owner_id')`` so a vector
lookup enters only that owner's HNSW buckets. The embedding is a property on
the vertex, written in the same statement or transaction as the vertex and
its edges.

FalkorDB stays the default. This module does not import FalkorDB.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from graph_memory_mcp import __version__
from graph_memory_mcp.graph_memory.backends.arcade_ops import ArcadeOps
from graph_memory_mcp.graph_memory.cache import CacheManager

logger = logging.getLogger(__name__)

_DB_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_OWNER = re.compile(r"^[a-zA-Z0-9_@-]+$")
VERTEX_TYPES = ("Fact", "Entity", "Collection", "FactVersion")
VECTOR_TYPES = ("Fact", "Entity")
BUCKETS = 32


class ArcadeDBError(RuntimeError):
    """ArcadeDB rejected a command or could not be reached."""


class ArcadeDBClient(ArcadeOps):
    """HTTP client for one ArcadeDB database shared by every owner."""

    def __init__(self, config):
        self.config = config
        self.cache = CacheManager(config)
        self._embedding_service: Any | None = None
        self.start_time = time.time()
        self._lock = threading.Lock()
        self._schema_ready = False
        self._vector_dim: Dict[str, int] = {}
        self._edge_types: set[str] = set()
        self.last_vector_search: Dict[str, Any] = {}
        host = getattr(config, "arcade_host", None) or "localhost"
        port = int(getattr(config, "arcade_port", None) or 2480)
        self._base = f"http://{host}:{port}"
        self._user = getattr(config, "arcade_user", None) or "root"
        self._password = getattr(config, "arcade_password", None) or ""
        database = getattr(config, "arcade_database", None) or "memory"
        if not _DB_NAME.match(str(database)):
            raise ValueError(f"Invalid ArcadeDB database name: {database!r}")
        self.database = str(database)
        token = base64.b64encode(f"{self._user}:{self._password}".encode()).decode()
        self._auth = f"Basic {token}"
        logger.info(
            "ArcadeDB client initialized (url=%s, database=%s, layout=partitioned-owner)",
            self._base,
            self.database,
        )

    def owner_literal(self, owner_id: str) -> str:
        """Owner id safe to inline. Partition pruning only sees a SQL literal."""
        if not isinstance(owner_id, str) or not _OWNER.match(owner_id):
            raise ValueError("Invalid owner_id format (use alphanumeric, -, _, @)")
        return owner_id

    def connect(self) -> bool:
        try:
            self.ensure_ready()
            self.query("SELECT name FROM schema:types LIMIT 1")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to connect to ArcadeDB: %s", exc)
            return False

    def health_check(self) -> Dict[str, Any]:
        try:
            self.query("SELECT name FROM schema:types LIMIT 1")
            return {
                "status": "healthy",
                "arcade_connected": True,
                "falkordb_connected": False,
                "backend": "arcadedb",
                "version": __version__,
                "uptime": time.time() - self.start_time,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "unhealthy",
                "arcade_connected": False,
                "falkordb_connected": False,
                "backend": "arcadedb",
                "error": str(exc),
            }

    @property
    def redis_client(self) -> None:
        """Job locks stay optional. ArcadeDB itself is the multi-client server."""
        return None

    def set_embedding_service(self, service: Any) -> None:
        self._embedding_service = service
        logger.info(
            "Embedding service attached (dimension=%s)",
            getattr(service, "dimension", 0),
        )

    def get_embedding(self, text: str, kind: str = "passage") -> List[float]:
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
        self, texts: List[str], kind: str = "passage"
    ) -> List[List[float]]:
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

    def ensure_ready(self) -> None:
        if self._schema_ready:
            return
        with self._lock:
            if self._schema_ready:
                return
            self.ensure_database()
            for label in VERTEX_TYPES:
                self._ensure_vertex_type(label)
            self._ensure_meta_type()
            self._load_vector_dims()
            self._schema_ready = True

    def ensure_database(self) -> None:
        try:
            self._server(f"create database {self.database}")
        except ArcadeDBError as exc:
            if "already exists" not in str(exc).lower():
                raise

    def drop_database(self) -> None:
        self._schema_ready = False
        self._vector_dim.clear()
        self._edge_types.clear()
        try:
            self._server(f"drop database {self.database}")
        except ArcadeDBError as exc:
            if "not found" not in str(exc).lower() and "does not exist" not in str(exc).lower():
                raise

    def _ensure_vertex_type(self, label: str) -> None:
        self.command(f"CREATE VERTEX TYPE {label} IF NOT EXISTS")
        self.command(f"CREATE PROPERTY {label}.owner_id IF NOT EXISTS STRING")
        self.command(f"CREATE PROPERTY {label}.uid IF NOT EXISTS STRING")
        if label in VECTOR_TYPES:
            self.command(
                f"CREATE PROPERTY {label}.embedding IF NOT EXISTS ARRAY_OF_FLOATS"
            )
            self.command(f"CREATE PROPERTY {label}.project IF NOT EXISTS STRING")
        strategy = self._bucket_strategy(label)
        if strategy != "partitioned":
            self.command(f"CREATE INDEX IF NOT EXISTS ON {label} (owner_id) UNIQUE")
            for i in range(BUCKETS):
                bucket = f"{label.lower()}_p{i:02d}"
                self.command(f"ALTER TYPE {label} BUCKET +{bucket}")
            self.command(
                f"ALTER TYPE {label} BucketSelectionStrategy `partitioned('owner_id')`"
            )
            self.command(f"DROP INDEX `{label}[owner_id]`")
        self.command(f"CREATE INDEX IF NOT EXISTS ON {label} (owner_id, uid) UNIQUE")

    def _ensure_meta_type(self) -> None:
        self.command("CREATE VERTEX TYPE GmMeta IF NOT EXISTS")
        self.command("CREATE PROPERTY GmMeta.label IF NOT EXISTS STRING")
        self.command("CREATE PROPERTY GmMeta.dimensions IF NOT EXISTS INTEGER")
        self.command("CREATE INDEX IF NOT EXISTS ON GmMeta (label) UNIQUE")

    def _bucket_strategy(self, label: str) -> str:
        rows = self.command(
            "var t = database.getSchema().getType('"
            + label
            + "'); t == null ? 'missing' : t.getBucketSelectionStrategy().getName()",
            language="js",
        )
        if not rows:
            return "missing"
        value = rows[0].get("value") if isinstance(rows[0], dict) else rows[0]
        return str(value or "missing")

    def _load_vector_dims(self) -> None:
        rows = self.query("SELECT label, dimensions FROM GmMeta")
        for row in rows:
            label = row.get("label")
            dim = row.get("dimensions")
            if label and dim:
                self._vector_dim[str(label)] = int(dim)

    def _index_exists(self, label: str) -> bool:
        rows = self.query(
            "SELECT name, indexType FROM schema:indexes WHERE name = :name",
            {"name": f"{label}[embedding]"},
        )
        return any(str(row.get("indexType") or "") == "LSM_VECTOR" for row in rows)

    def ensure_vector_index(self, label: str, dimension: int) -> None:
        """Create the cosine HNSW index, or reject a different dimension."""
        if label not in VECTOR_TYPES:
            raise ValueError(f"Vector search is not indexed for {label}")
        dim = int(dimension)
        if dim <= 0:
            raise ValueError("Embedding dimension must be positive")
        self.ensure_ready()
        known = self._vector_dim.get(label)
        if known is not None and known != dim:
            raise ValueError(
                f"Embedding dimension {dim} does not match index dimension {known} for {label}"
            )
        if self._index_exists(label):
            if known is None:
                self._vector_dim[label] = dim
                self._store_vector_dim(label, dim)
            return
        metadata = json.dumps({"dimensions": dim, "similarity": "COSINE"})
        self.command(
            f"CREATE INDEX IF NOT EXISTS ON {label} (embedding) LSM_VECTOR METADATA {metadata}"
        )
        self._vector_dim[label] = dim
        self._store_vector_dim(label, dim)

    def _store_vector_dim(self, label: str, dimension: int) -> None:
        existing = self.query(
            "SELECT @rid AS rid FROM GmMeta WHERE label = :label",
            {"label": label},
        )
        if existing:
            self.command(
                "UPDATE GmMeta SET dimensions = :dim WHERE label = :label",
                {"dim": int(dimension), "label": label},
            )
            return
        self.command(
            "INSERT INTO GmMeta SET label = :label, dimensions = :dim",
            {"label": label, "dim": int(dimension)},
        )

    def ensure_vector_indexes_if_missing(
        self,
        *,
        owner_id: str = "default",
        dimension: int | None = None,
        similarity_function: str = "cosine",
    ) -> Dict[str, bool]:
        del owner_id, similarity_function
        dim = int(dimension or getattr(self._embedding_service, "dimension", 0) or 0)
        if dim <= 0:
            return self.get_vector_index_status()
        for label in VECTOR_TYPES:
            if not self.get_vector_index_status().get(label):
                self.ensure_vector_index(label, dim)
        return self.get_vector_index_status()

    def ensure_search_indexes_if_missing(
        self,
        *,
        owner_id: str = "default",
        dimension: int | None = None,
        similarity_function: str = "cosine",
    ) -> Dict[str, Any]:
        vector_status = self.ensure_vector_indexes_if_missing(
            owner_id=owner_id,
            dimension=dimension,
            similarity_function=similarity_function,
        )
        for label in VECTOR_TYPES:
            self.command(f"CREATE INDEX IF NOT EXISTS ON {label} (project) NOTUNIQUE")
        return {"vector": vector_status}

    def get_vector_index_status(self, owner_id: str = "default") -> Dict[str, Any]:
        del owner_id
        status = {"Fact": False, "Entity": False}
        try:
            self.ensure_database()
            rows = self.query("SELECT name, indexType, typeName FROM schema:indexes")
            for row in rows:
                if str(row.get("indexType") or "") != "LSM_VECTOR":
                    continue
                label = str(row.get("typeName") or "")
                if label in status and str(row.get("name") or "").endswith("[embedding]"):
                    status[label] = True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to get vector index status: %s", exc)
        return status

    def create_vector_index(
        self,
        dimension: int = 768,
        similarity_function: str = "cosine",
        owner_id: str = "default",
    ) -> bool:
        del similarity_function, owner_id
        self.ensure_vector_index("Fact", dimension)
        return True

    def create_entity_vector_index(
        self,
        dimension: int = 768,
        similarity_function: str = "cosine",
        owner_id: str = "default",
    ) -> bool:
        del similarity_function, owner_id
        self.ensure_vector_index("Entity", dimension)
        return True

    def count_labeled(self, node_type: str, owner_id: str) -> int:
        owner = self.owner_literal(owner_id)
        rows = self.query(
            f"SELECT count(*) AS c FROM {node_type} WHERE owner_id = '{owner}'"
        )
        if not rows:
            return 0
        return int(rows[0].get("c") or 0)

    def ensure_edge_type(self, rel_type: str) -> None:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", rel_type):
            raise ValueError(f"Invalid relation type: {rel_type!r}")
        if rel_type in self._edge_types:
            return
        self.command(f"CREATE EDGE TYPE {rel_type} IF NOT EXISTS")
        self._edge_types.add(rel_type)

    @contextmanager
    def transaction(self) -> Iterator[str]:
        """One HTTP session. Commit writes the vertex, its vector, and edges together."""
        self.ensure_database()
        session = self._begin()
        try:
            yield session
        except Exception:
            try:
                self._rollback(session)
            except Exception:  # noqa: BLE001
                logger.exception("ArcadeDB rollback failed")
            raise
        else:
            self._commit(session)

    def query(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        language: str = "sql",
        session: str | None = None,
    ) -> List[Dict[str, Any]]:
        return self._sql("query", sql, params, language=language, session=session)

    def command(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        language: str = "sql",
        session: str | None = None,
    ) -> List[Dict[str, Any]]:
        return self._sql("command", sql, params, language=language, session=session)

    def _sql(
        self,
        kind: str,
        sql: str,
        params: Optional[Dict[str, Any]],
        *,
        language: str,
        session: str | None,
    ) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"language": language, "command": sql}
        if params:
            payload["params"] = params
        body = self._request(
            "POST",
            f"/api/v1/{kind}/{self.database}",
            payload,
            session=session,
        )
        result = body.get("result") if isinstance(body, dict) else None
        if not result:
            return []
        if isinstance(result, list):
            return [row if isinstance(row, dict) else {"value": row} for row in result]
        if isinstance(result, dict):
            return [result]
        return [{"value": result}]

    def _begin(self) -> str:
        status, headers, _raw = self._raw("POST", f"/api/v1/begin/{self.database}")
        session = headers.get("arcadedb-session-id")
        if status not in (200, 204) or not session:
            raise ArcadeDBError("ArcadeDB did not start a transaction")
        return session

    def _commit(self, session: str) -> None:
        self._raw("POST", f"/api/v1/commit/{self.database}", session=session)

    def _rollback(self, session: str) -> None:
        self._raw("POST", f"/api/v1/rollback/{self.database}", session=session)

    def _server(self, command: str) -> None:
        self._request("POST", "/api/v1/server", {"command": command})

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        session: str | None = None,
    ) -> Dict[str, Any]:
        _status, _headers, raw = self._raw(method, path, payload, session=session)
        if not raw:
            return {}
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ArcadeDBError(raw[:500]) from exc
        return body if isinstance(body, dict) else {"result": body}

    def _raw(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        session: str | None = None,
    ) -> tuple[int, Dict[str, str], str]:
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(self._base + path, data=data, method=method)
        req.add_header("Authorization", self._auth)
        if payload is not None:
            req.add_header("Content-Type", "application/json")
        if session:
            req.add_header("arcadedb-session-id", session)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = response.read().decode()
                return response.status, dict(response.headers), raw
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            message = detail
            try:
                parsed = json.loads(detail)
                message = parsed.get("detail") or parsed.get("error") or detail
            except json.JSONDecodeError:
                pass
            raise ArcadeDBError(message) from exc
        except urllib.error.URLError as exc:
            raise ArcadeDBError(str(exc.reason)) from exc
