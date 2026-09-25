"""Graph store protocol. Handlers depend on this, not on a database driver."""

from __future__ import annotations

from typing import Any, Protocol


class GraphStore(Protocol):
    """Operations the MCP handlers and jobs need from a graph backend.

    FalkorDB implements these today. ArcadeDB implements the same methods and
    owns its own SQL.
    """

    config: Any
    cache: Any

    def connect(self) -> bool: ...

    def health_check(self) -> dict[str, Any]: ...

    def list_owners(self) -> list[str]: ...

    def delete_owner_graph(self, owner_id: str) -> bool: ...

    def get_embedding(self, text: str, kind: str = "passage") -> list[float]: ...

    def get_embeddings_batch(
        self, texts: list[str], kind: str = "passage"
    ) -> list[list[float]]: ...

    def ensure_search_indexes_if_missing(
        self,
        *,
        owner_id: str = "default",
        dimension: int | None = None,
        similarity_function: str = "cosine",
    ) -> dict[str, Any]: ...

    def ensure_vector_indexes_if_missing(
        self,
        *,
        owner_id: str = "default",
        dimension: int | None = None,
        similarity_function: str = "cosine",
    ) -> dict[str, bool]: ...

    def get_vector_index_status(self, owner_id: str = "default") -> dict[str, Any]: ...

    def set_embedding_service(self, service: Any) -> None: ...

    def backfill_all_owners(self) -> None: ...
