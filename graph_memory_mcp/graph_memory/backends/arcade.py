"""ArcadeDB graph adapter.

ArcadeDB is a server: many clients share it. Each owner_id is its own database,
named ``{ARCADE_DATABASE}_{owner_id}``, the same layout as a Falkor graph.
That database holds only that owner's vertices, edges, and HNSW indexes.
The embedding is a property on the vertex, written in the same statement or
transaction as the vertex and its edges.

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
import urllib.parse
import urllib.request
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, List, Optional

from graph_memory_mcp import __version__
from graph_memory_mcp.graph_memory.backends.arcade_ops import ArcadeOps
from graph_memory_mcp.graph_memory.cache import CacheManager

logger = logging.getLogger(__name__)

_DB_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_OWNER = re.compile(r"^[a-zA-Z0-9_@-]+$")
VERTEX_TYPES = ("Fact", "Entity", "Collection", "FactVersion")
VECTOR_TYPES = ("Fact", "Entity")
_ACTIVE_DB: ContextVar[str | None] = ContextVar("arcade_owner_db", default=None)


class ArcadeDBError(RuntimeError):
    """ArcadeDB rejected a command or could not be reached."""


class ArcadeDBClient(ArcadeOps):
    """HTTP client. One ArcadeDB database per owner_id."""

    def __init__(self, config):
        self.config = config
        self.cache = CacheManager(config)
        self._embedding_service: Any | None = None
        self.start_time = time.time()
        self._lock = threading.Lock()
        self._ready: set[str] = set()
        self._vector_dim: Dict[str, int] = {}
        self._model_dim: int | None = None
        self._edge_types: Dict[str, set[str]] = {}
        self.last_vector_search: Dict[str, Any] = {}
        host = getattr(config, "arcade_host", None) or "localhost"
        port = int(getattr(config, "arcade_port", None) or 2480)
        self._base = f"http://{host}:{port}"
        self._user = getattr(config, "arcade_user", None) or "root"
        self._password = getattr(config, "arcade_password", None) or ""
        database = getattr(config, "arcade_database", None) or "memory"
        if not _DB_NAME.match(str(database)):
            raise ValueError(f"Invalid ArcadeDB database name: {database!r}")
        self.database_prefix = str(database)
        token = base64.b64encode(f"{self._user}:{self._password}".encode()).decode()
        self._auth = f"Basic {token}"
        logger.info(
            "ArcadeDB client initialized (url=%s, database prefix=%s, layout=database-per-owner)",
            self._base,
            self.database_prefix,
        )

    def owner_literal(self, owner_id: str) -> str:
        """Owner id safe to interpolate. The database name is the isolation boundary."""
        if not isinstance(owner_id, str) or not _OWNER.match(owner_id):
            raise ValueError("Invalid owner_id format (use alphanumeric, -, _, @)")
        return owner_id

    def database_name(self, owner_id: str) -> str:
        """``{ARCADE_DATABASE}_{owner_id}``, matching Falkor's graph name."""
        return f"{self.database_prefix}_{self.owner_literal(owner_id)}"

    @contextmanager
    def owner_scope(self, owner_id: str) -> Iterator[str]:
        """Create the owner database if needed and point later SQL at it."""
        name = self.database_name(owner_id)
        current = _ACTIVE_DB.get()
        if current == name:
            yield name
            return
        self._create_database(name)
        token = _ACTIVE_DB.set(name)
        try:
            self._ensure_schema(name)
            yield name
        finally:
            _ACTIVE_DB.reset(token)

    def connect(self) -> bool:
        try:
            self.list_database_names()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to connect to ArcadeDB: %s", exc)
            return False

    def health_check(self) -> Dict[str, Any]:
        try:
            self.list_database_names()
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
        name = self._require_db()
        self._ensure_schema(name)

    def _create_database(self, name: str) -> None:
        try:
            self._server(f"create database {name}")
        except ArcadeDBError as exc:
            if "already exists" not in str(exc).lower():
                raise

    def drop_database(self) -> None:
        """Drop every owner database for this prefix. Used by tests."""
        prefix = self.database_prefix + "_"
        for name in self.list_database_names():
            if not name.startswith(prefix):
                continue
            try:
                self._server(f"drop database {name}")
            except ArcadeDBError as exc:
                message = str(exc).lower()
                if "not found" not in message and "does not exist" not in message:
                    raise
        self._ready.clear()
        self._edge_types.clear()
        self._vector_dim.clear()

    def list_database_names(self) -> List[str]:
        body = self._request("GET", "/api/v1/databases")
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, list):
            return []
        return [str(name) for name in result]

    def _ensure_schema(self, name: str) -> None:
        if name in self._ready:
            return
        with self._lock:
            if name in self._ready:
                return
            if _ACTIVE_DB.get() != name:
                raise ArcadeDBError(f"Schema setup left database {name}")
            for label in VERTEX_TYPES:
                self._ensure_vertex_type(label)
            self._ensure_meta_type()
            self._load_vector_dims()
            if self._model_dim:
                for label in VECTOR_TYPES:
                    if not self._index_exists(label):
                        self._ensure_one_vector_index(label, self._model_dim)
            self._ready.add(name)

    def _ensure_vertex_type(self, label: str) -> None:
        self.command(f"CREATE VERTEX TYPE {label} IF NOT EXISTS")
        self.command(f"CREATE PROPERTY {label}.owner_id IF NOT EXISTS STRING")
        self.command(f"CREATE PROPERTY {label}.uid IF NOT EXISTS STRING")
        self.command(f"CREATE INDEX IF NOT EXISTS ON {label} (uid) UNIQUE")
        if label in VECTOR_TYPES:
            self.command(
                f"CREATE PROPERTY {label}.embedding IF NOT EXISTS ARRAY_OF_FLOATS"
            )
            self.command(f"CREATE PROPERTY {label}.project IF NOT EXISTS STRING")

    def _ensure_meta_type(self) -> None:
        self.command("CREATE VERTEX TYPE GmMeta IF NOT EXISTS")
        self.command("CREATE PROPERTY GmMeta.label IF NOT EXISTS STRING")
        self.command("CREATE PROPERTY GmMeta.dimensions IF NOT EXISTS INTEGER")
        self.command("CREATE INDEX IF NOT EXISTS ON GmMeta (label) UNIQUE")

    def _load_vector_dims(self) -> None:
        database = self._require_db()
        rows = self.query("SELECT label, dimensions FROM GmMeta")
        for row in rows:
            label = row.get("label")
            dim = row.get("dimensions")
            if not label or not dim:
                continue
            dim = int(dim)
            self._vector_dim[f"{database}:{label}"] = dim
            if self._model_dim is None:
                self._model_dim = dim

    def _index_exists(self, label: str) -> bool:
        rows = self.query(
            "SELECT name, indexType FROM schema:indexes WHERE name = :name",
            {"name": f"{label}[embedding]"},
        )
        return any(str(row.get("indexType") or "") == "LSM_VECTOR" for row in rows)

    def ensure_vector_index(self, label: str, dimension: int) -> None:
        """Create this database's cosine HNSW indexes, or reject another dimension."""
        if label not in VECTOR_TYPES:
            raise ValueError(f"Vector search is not indexed for {label}")
        dim = int(dimension)
        if dim <= 0:
            raise ValueError("Embedding dimension must be positive")
        self.ensure_ready()
        if self._model_dim is not None and self._model_dim != dim:
            raise ValueError(
                f"Embedding dimension {dim} does not match index dimension {self._model_dim}"
            )
        for vector_label in VECTOR_TYPES:
            self._ensure_one_vector_index(vector_label, dim)
        self._model_dim = dim

    def _ensure_one_vector_index(self, label: str, dimension: int) -> None:
        key = f"{self._require_db()}:{label}"
        known = self._vector_dim.get(key)
        if known is not None and known != dimension:
            raise ValueError(
                f"Embedding dimension {dimension} does not match index dimension {known} for {label}"
            )
        if self._index_exists(label):
            self._vector_dim[key] = dimension
            self._store_vector_dim(label, dimension)
            return
        metadata = json.dumps({"dimensions": dimension, "similarity": "COSINE"})
        self.command(
            f"CREATE INDEX IF NOT EXISTS ON {label} (embedding) LSM_VECTOR METADATA {metadata}"
        )
        self._vector_dim[key] = dimension
        self._store_vector_dim(label, dimension)

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
        del similarity_function
        with self.owner_scope(owner_id):
            dim = int(dimension or getattr(self._embedding_service, "dimension", 0) or 0)
            if dim <= 0:
                return self._vector_status_here()
            status = self._vector_status_here()
            for label in VECTOR_TYPES:
                if not status.get(label):
                    self.ensure_vector_index(label, dim)
            return self._vector_status_here()

    def ensure_search_indexes_if_missing(
        self,
        *,
        owner_id: str = "default",
        dimension: int | None = None,
        similarity_function: str = "cosine",
    ) -> Dict[str, Any]:
        with self.owner_scope(owner_id):
            vector_status = self.ensure_vector_indexes_if_missing(
                owner_id=owner_id,
                dimension=dimension,
                similarity_function=similarity_function,
            )
            for label in VECTOR_TYPES:
                self.command(f"CREATE INDEX IF NOT EXISTS ON {label} (project) NOTUNIQUE")
            return {"vector": vector_status}

    def get_vector_index_status(self, owner_id: str = "default") -> Dict[str, Any]:
        name = self.database_name(owner_id)
        if name not in set(self.list_database_names()):
            return {"Fact": False, "Entity": False}
        with self.owner_scope(owner_id):
            return self._vector_status_here()

    def _vector_status_here(self) -> Dict[str, bool]:
        status = {"Fact": False, "Entity": False}
        try:
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
        del similarity_function
        with self.owner_scope(owner_id):
            self.ensure_vector_index("Fact", dimension)
        return True

    def create_entity_vector_index(
        self,
        dimension: int = 768,
        similarity_function: str = "cosine",
        owner_id: str = "default",
    ) -> bool:
        del similarity_function
        with self.owner_scope(owner_id):
            self.ensure_vector_index("Entity", dimension)
        return True

    def count_labeled(self, node_type: str, owner_id: str) -> int:
        owner = self.owner_literal(owner_id)
        with self.owner_scope(owner_id):
            rows = self.query(
                f"SELECT count(*) AS c FROM {node_type} WHERE owner_id = '{owner}'"
            )
        if not rows:
            return 0
        return int(rows[0].get("c") or 0)

    def ensure_edge_type(self, rel_type: str) -> None:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", rel_type):
            raise ValueError(f"Invalid relation type: {rel_type!r}")
        database = self._require_db()
        known = self._edge_types.setdefault(database, set())
        if rel_type in known:
            return
        self.command(f"CREATE EDGE TYPE {rel_type} IF NOT EXISTS")
        known.add(rel_type)

    @contextmanager
    def transaction(self) -> Iterator[str]:
        """One HTTP session. Commit writes the vertex, its vector, and edges together."""
        database = self._require_db()
        session = self._begin(database)
        try:
            yield session
        except Exception:
            try:
                self._rollback(database, session)
            except Exception:  # noqa: BLE001
                logger.exception("ArcadeDB rollback failed")
            raise
        else:
            self._commit(database, session)

    def _require_db(self) -> str:
        name = _ACTIVE_DB.get()
        if not name:
            raise ArcadeDBError("No owner database selected")
        return name

    def _db_path(self, database: str | None = None) -> str:
        name = database or self._require_db()
        return urllib.parse.quote(name, safe="")

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
            f"/api/v1/{kind}/{self._db_path()}",
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

    def _begin(self, database: str) -> str:
        status, headers, _raw = self._raw(
            "POST", f"/api/v1/begin/{self._db_path(database)}"
        )
        session = headers.get("arcadedb-session-id")
        if status not in (200, 204) or not session:
            raise ArcadeDBError("ArcadeDB did not start a transaction")
        return session

    def _commit(self, database: str, session: str) -> None:
        self._raw("POST", f"/api/v1/commit/{self._db_path(database)}", session=session)

    def _rollback(self, database: str, session: str) -> None:
        self._raw("POST", f"/api/v1/rollback/{self._db_path(database)}", session=session)

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
