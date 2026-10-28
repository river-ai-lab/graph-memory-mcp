"""Memory adapters. Optional libraries are skipped when they are not installed."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from benchlib.dataset import Dataset, Fact

_TOKENS = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Hit:
    fact_id: str
    text: str
    score: float


class MemoryAdapter(Protocol):
    name: str
    retrieves: bool

    def reset(self) -> None: ...

    def ingest(self, dataset: Dataset) -> None: ...

    def search(
        self, query: str, k: int, *, include_outdated: bool = False
    ) -> list[Hit]: ...


class AdapterNotInstalled(Exception):
    """Raised when an optional library is absent."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _fact_id_for_text(text: str, facts: tuple[Fact, ...]) -> str:
    folded = text.strip()
    for fact in facts:
        if fact.text == folded or fact.text in folded or folded in fact.text:
            return fact.id
    return ""


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _tokens(text: str) -> list[str]:
    return _TOKENS.findall(text.lower())


def _token_hash(token: str, seed: int) -> int:
    digest = hashlib.sha256(f"{seed}:{token}".encode()).digest()
    return int.from_bytes(digest[:8], "little")


class HashingEmbedder:
    """Seeded feature-hashing vectors. Deterministic and local."""

    def __init__(self, *, dim: int = 256, seed: int = 1729) -> None:
        self.dim = dim
        self.seed = seed

    def embed(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float64)
        for token in _tokens(text):
            hashed = _token_hash(token, self.seed)
            index = hashed % self.dim
            sign = 1.0 if (hashed >> 8) & 1 else -1.0
            vector[index] += sign
        norm = float(np.linalg.norm(vector))
        if norm:
            vector /= norm
        return vector


class NoMemoryAdapter:
    """Answer from the question alone. Retrieval is not run."""

    name = "none"
    retrieves = False

    def reset(self) -> None:
        return None

    def ingest(self, dataset: Dataset) -> None:
        return None

    def search(
        self, query: str, k: int, *, include_outdated: bool = False
    ) -> list[Hit]:
        return []


class RagAdapter:
    """Plain vector retrieval over every fact, including outdated facts."""

    name = "rag"
    retrieves = True

    def __init__(self, *, seed: int = 1729, dim: int = 256) -> None:
        self.embedder = HashingEmbedder(dim=dim, seed=seed)
        self._docs: list[tuple[str, str, np.ndarray]] = []

    def reset(self) -> None:
        self._docs = []

    def ingest(self, dataset: Dataset) -> None:
        self._docs = [
            (fact.id, fact.text, self.embedder.embed(fact.text))
            for fact in dataset.facts
        ]

    def search(
        self, query: str, k: int, *, include_outdated: bool = False
    ) -> list[Hit]:
        del include_outdated  # RAG keeps the whole corpus; lifecycle is not filtered.
        if k <= 0 or not self._docs:
            return []
        query_vector = self.embedder.embed(query)
        ranked = sorted(
            (
                (float(np.dot(query_vector, vector)), fact_id, text)
                for fact_id, text, vector in self._docs
            ),
            key=lambda item: (-item[0], item[1]),
        )
        return [
            Hit(fact_id=fact_id, text=text, score=score)
            for score, fact_id, text in ranked[:k]
        ]


class GraphMemoryAdapter:
    """Graph Memory MCP via the Python API. Does not change server code."""

    name = "graph"
    retrieves = True

    def __init__(self, *, owner_id: str = "llmbench", server: Any = None) -> None:
        self.owner_id = owner_id
        self.server = server
        self._ids: dict[str, str] = {}
        self.ingest_notes: list[str] = []

    def connect(self) -> None:
        if self.server is not None:
            return
        from graph_memory_mcp.config import load_mcp_server_config
        from graph_memory_mcp.server import GraphMemoryMCP

        self.server = GraphMemoryMCP(load_mcp_server_config())

    def reset(self) -> None:
        self.connect()
        deleted = self.server.db_client.delete_owner_graph(self.owner_id)
        if not deleted:
            raise RuntimeError(f"failed to reset owner {self.owner_id}")
        self._ids = {}
        self.ingest_notes = []

    def ingest(self, dataset: Dataset) -> None:
        self.connect()
        self._ids = {}
        for fact in dataset.facts:
            result = self.server.create_node(
                text=fact.text,
                node_type="Fact",
                metadata={
                    "fact_id": fact.id,
                    "valid_from": fact.valid_from or "",
                    "valid_until": fact.valid_until or "",
                    "distractor": fact.distractor,
                },
                owner_id=self.owner_id,
                check_duplicates=False,
            )
            if not result.get("success", True):
                self.ingest_notes.append(f"{fact.id}: {result.get('error', result)}")
                continue
            node_id = (result.get("node") or {}).get("node_id")
            if not node_id:
                self.ingest_notes.append(f"{fact.id}: missing node_id")
                continue
            self._ids[fact.id] = node_id
            if fact.status == "outdated":
                marked = self.server.mark_outdated(
                    fact_id=node_id,
                    reason=f"Outdated as of {fact.valid_until or 'unknown'}",
                    owner_id=self.owner_id,
                )
                if not marked.get("success", True):
                    self.ingest_notes.append(f"{fact.id}: mark_outdated failed")
        for fact in dataset.facts:
            self._link(fact)

    def _link(self, fact: Fact) -> None:
        source = self._ids.get(fact.id)
        if not source:
            return
        pairs: list[tuple[str | None, str]] = [
            (fact.supersedes, "FOLLOWS_FROM"),
            (fact.follows_from, "FOLLOWS_FROM"),
            (fact.contradicts, "CONTRADICTS"),
        ]
        for target_key, relation in pairs:
            if not target_key:
                continue
            target = self._ids.get(target_key)
            if not target:
                self.ingest_notes.append(f"{fact.id}: missing target {target_key}")
                continue
            result = self.server.create_relation(
                from_id=source,
                to_id=target,
                relation_type=relation,
                owner_id=self.owner_id,
            )
            if not result.get("success", True):
                self.ingest_notes.append(
                    f"{fact.id}: {relation} -> {target_key} failed"
                )

    def search(
        self, query: str, k: int, *, include_outdated: bool = False
    ) -> list[Hit]:
        self.connect()
        result = self.server.search(
            query=query,
            owner_id=self.owner_id,
            limit=k,
            node_types=["Fact"],
            include_outdated=include_outdated,
        )
        if not result.get("success", True):
            raise RuntimeError(result.get("error") or "graph search failed")
        hits: list[Hit] = []
        for row in result.get("results") or []:
            metadata = row.get("metadata") or {}
            if isinstance(metadata, str):
                metadata = {}
            fact_id = str(metadata.get("fact_id") or row.get("node_id") or "")
            hits.append(
                Hit(
                    fact_id=fact_id,
                    text=str(row.get("text") or ""),
                    score=float(row.get("similarity") or 0.0),
                )
            )
        return hits


class _OptionalAdapter:
    """Shared skip behavior. Subclasses run only when their library imports."""

    name = "optional"
    retrieves = True
    modules: tuple[str, ...] = ()

    def reset(self) -> None:
        self._require()

    def ingest(self, dataset: Dataset) -> None:
        self._require()

    def search(
        self, query: str, k: int, *, include_outdated: bool = False
    ) -> list[Hit]:
        self._require()
        return []

    def _require(self) -> None:
        if not any(_module_available(name) for name in self.modules):
            raise AdapterNotInstalled(f"{self.name} is not installed")


class Mem0Adapter(_OptionalAdapter):
    name = "mem0"
    modules = ("mem0",)

    def __init__(self, *, user_id: str = "llmbench") -> None:
        self.user_id = user_id
        self._memory: Any = None
        self._facts: tuple[Fact, ...] = ()

    def reset(self) -> None:
        self._require()
        from mem0 import Memory

        self._memory = Memory()
        self._facts = ()

    def ingest(self, dataset: Dataset) -> None:
        self._require()
        assert self._memory is not None
        self._facts = dataset.facts
        for fact in dataset.facts:
            self._memory.add(
                fact.text,
                user_id=self.user_id,
                metadata={"fact_id": fact.id},
            )

    def search(
        self, query: str, k: int, *, include_outdated: bool = False
    ) -> list[Hit]:
        del include_outdated
        self._require()
        assert self._memory is not None
        raw = self._memory.search(query, user_id=self.user_id, limit=k)
        rows = raw.get("results", raw) if isinstance(raw, dict) else raw
        hits: list[Hit] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            metadata = row.get("metadata") or {}
            text = str(row.get("memory") or row.get("text") or "")
            fact_id = str(metadata.get("fact_id") or "") or _fact_id_for_text(
                text, self._facts
            )
            score = float(row.get("score") or 0.0)
            hits.append(Hit(fact_id=fact_id, text=text, score=score))
        return hits[:k]


class GraphitiAdapter(_OptionalAdapter):
    """Local Graphiti. Skips unless a Neo4j URI is configured. ``zep`` is an alias."""

    name = "graphiti"
    modules = ("graphiti_core",)

    def __init__(self) -> None:
        self._client: Any = None
        self._facts: tuple[Fact, ...] = ()

    def reset(self) -> None:
        self._require()
        uri = os.environ.get("GRAPHITI_NEO4J_URI", "").strip()
        if not uri:
            raise AdapterNotInstalled(
                "graphiti is installed but GRAPHITI_NEO4J_URI is not set"
            )
        from graphiti_core import Graphiti

        self._client = Graphiti(
            uri,
            os.environ.get("GRAPHITI_NEO4J_USER", "neo4j"),
            os.environ.get("GRAPHITI_NEO4J_PASSWORD", ""),
        )
        self._facts = ()

    def ingest(self, dataset: Dataset) -> None:
        self._require()
        if self._client is None:
            raise AdapterNotInstalled("graphiti client is not connected")
        import asyncio
        from datetime import datetime, timezone

        from graphiti_core.nodes import EpisodeType

        self._facts = dataset.facts

        async def _add() -> None:
            await self._client.build_indices_and_constraints()
            for fact in dataset.facts:
                await self._client.add_episode(
                    name=fact.id,
                    episode_body=fact.text,
                    source=EpisodeType.text,
                    source_description="llm-benchmark",
                    reference_time=datetime.now(timezone.utc),
                )

        asyncio.run(_add())

    def search(
        self, query: str, k: int, *, include_outdated: bool = False
    ) -> list[Hit]:
        del include_outdated
        self._require()
        if self._client is None:
            raise AdapterNotInstalled("graphiti client is not connected")
        import asyncio

        rows = asyncio.run(self._client.search(query)) or []
        hits: list[Hit] = []
        for row in list(rows)[:k]:
            text = str(getattr(row, "fact", None) or getattr(row, "text", None) or row)
            hits.append(
                Hit(fact_id=_fact_id_for_text(text, self._facts), text=text, score=0.0)
            )
        return hits


class LettaAdapter(_OptionalAdapter):
    name = "letta"
    modules = ("letta_client", "letta")

    def __init__(self) -> None:
        self._client: Any = None
        self._agent_id: str | None = None
        self._facts: tuple[Fact, ...] = ()

    def reset(self) -> None:
        self._require()
        base_url = os.environ.get("LETTA_BASE_URL", "").strip()
        if not base_url:
            raise AdapterNotInstalled(
                "letta is installed but LETTA_BASE_URL is not set"
            )
        if _module_available("letta_client"):
            from letta_client import Letta

            self._client = Letta(base_url=base_url)
        else:
            from letta import Letta

            self._client = Letta(base_url=base_url)
        self._agent_id = None
        self._facts = ()

    def ingest(self, dataset: Dataset) -> None:
        self._require()
        if self._client is None:
            raise AdapterNotInstalled("letta client is not connected")
        self._facts = dataset.facts
        agent = self._client.agents.create(name="llmbench")
        self._agent_id = str(agent.id)
        for fact in dataset.facts:
            self._client.agents.passages.create(agent_id=self._agent_id, text=fact.text)

    def search(
        self, query: str, k: int, *, include_outdated: bool = False
    ) -> list[Hit]:
        del include_outdated
        self._require()
        if self._client is None or self._agent_id is None:
            raise AdapterNotInstalled("letta client is not connected")
        rows = self._client.agents.passages.list(
            agent_id=self._agent_id, query=query, limit=k
        )
        hits: list[Hit] = []
        for row in list(rows or [])[:k]:
            text = str(getattr(row, "text", None) or row)
            hits.append(
                Hit(fact_id=_fact_id_for_text(text, self._facts), text=text, score=0.0)
            )
        return hits


class CogneeAdapter(_OptionalAdapter):
    name = "cognee"
    modules = ("cognee",)

    def __init__(self) -> None:
        self._facts: tuple[Fact, ...] = ()

    def reset(self) -> None:
        self._require()
        if os.environ.get("COGNEE_LOCAL", "").strip() != "1":
            raise AdapterNotInstalled(
                "cognee is installed but COGNEE_LOCAL=1 is not set"
            )
        self._facts = ()

    def ingest(self, dataset: Dataset) -> None:
        self._require()
        import asyncio

        import cognee

        self._facts = dataset.facts

        async def _add() -> None:
            for fact in dataset.facts:
                await cognee.add(fact.text)
            await cognee.cognify()

        asyncio.run(_add())

    def search(
        self, query: str, k: int, *, include_outdated: bool = False
    ) -> list[Hit]:
        del include_outdated
        self._require()
        import asyncio

        import cognee

        rows = asyncio.run(cognee.search(query)) or []
        hits: list[Hit] = []
        for row in list(rows)[:k]:
            text = str(row)
            hits.append(
                Hit(fact_id=_fact_id_for_text(text, self._facts), text=text, score=0.0)
            )
        return hits


_BUILDERS = {
    "none": lambda **_: NoMemoryAdapter(),
    "rag": lambda **kwargs: RagAdapter(seed=int(kwargs.get("seed", 1729))),
    "graph": lambda **kwargs: GraphMemoryAdapter(
        owner_id=str(kwargs.get("owner_id", "llmbench"))
    ),
    "mem0": lambda **_: Mem0Adapter(),
    "graphiti": lambda **_: GraphitiAdapter(),
    "zep": lambda **_: GraphitiAdapter(),
    "letta": lambda **_: LettaAdapter(),
    "cognee": lambda **_: CogneeAdapter(),
}


def availability(name: str) -> tuple[bool, str]:
    """Return whether a mode can run. Optional modes skip when the library is missing."""
    if name not in _BUILDERS:
        return False, f"unknown mode {name}"
    if name in {"none", "rag", "graph"}:
        return True, ""
    modules = {
        "mem0": ("mem0",),
        "graphiti": ("graphiti_core",),
        "zep": ("graphiti_core",),
        "letta": ("letta_client", "letta"),
        "cognee": ("cognee",),
    }[name]
    if any(_module_available(module) for module in modules):
        return True, ""
    return False, f"{name} is not installed"


def build_adapter(name: str, **kwargs: Any) -> MemoryAdapter:
    ok, reason = availability(name)
    if not ok:
        raise AdapterNotInstalled(reason)
    return _BUILDERS[name](**kwargs)
