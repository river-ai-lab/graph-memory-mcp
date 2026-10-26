"""Shared embedding cache used by both graph clients."""

from graph_memory_mcp.graph_memory.backends.embedding_cache import (
    cached_embedding,
    cached_embeddings_batch,
)


class _Cache:
    def __init__(self) -> None:
        self.store: dict[str, list[float]] = {}

    def get_embedding(self, key: str):
        return self.store.get(key)

    def set_embedding(self, key: str, value: list[float]) -> None:
        self.store[key] = value


class _Service:
    def __init__(self, *, reject_kind: bool = False, fail: bool = False) -> None:
        self.reject_kind = reject_kind
        self.fail = fail
        self.calls: list[tuple] = []

    def get_embedding(self, text: str, kind: str = "passage") -> list[float]:
        self.calls.append(("one", text, kind))
        if self.fail:
            raise RuntimeError("down")
        if self.reject_kind:
            raise TypeError("kind")
        return [float(len(text)), 0.0]

    def get_embeddings_batch(self, texts: list[str], kind: str = "passage"):
        self.calls.append(("batch", tuple(texts), kind))
        if self.fail:
            raise RuntimeError("down")
        if self.reject_kind:
            raise TypeError("kind")
        return [[float(len(text))] for text in texts]


class _Legacy:
    def get_embedding(self, text: str) -> list[float]:
        return [0.5]

    def get_embeddings_batch(self, texts: list[str]):
        return [[0.5] for _ in texts]


class _Client:
    def __init__(self, service) -> None:
        self._embedding_service = service
        self.cache = _Cache()


def test_cached_embedding_reuses_kind_key() -> None:
    client = _Client(_Service())
    assert cached_embedding(client, "hi", kind="query") == [2.0, 0.0]
    assert cached_embedding(client, "hi", kind="query") == [2.0, 0.0]
    assert client._embedding_service.calls == [("one", "hi", "query")]
    assert "query:hi" in client.cache.store


def test_cached_embedding_falls_back_when_kind_is_rejected() -> None:
    client = _Client(_Legacy())
    assert cached_embedding(client, "hi", kind="query") == [0.5]
    assert cached_embeddings_batch(client, ["a", "b"], kind="query") == [[0.5], [0.5]]


def test_cached_embedding_returns_empty_on_failure() -> None:
    client = _Client(_Service(fail=True))
    assert cached_embedding(client, "hi") == []
    assert cached_embeddings_batch(client, ["a"]) == [[]]
    missing = _Client(None)
    assert cached_embedding(missing, "hi") == []
    assert cached_embeddings_batch(missing, ["a", "b"]) == [[], []]
