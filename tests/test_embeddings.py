"""ONNX embedding backend: selection, missing extra, parity with torch."""

from __future__ import annotations

import builtins

import numpy as np
import pytest
from pydantic import ValidationError

from graph_memory_mcp.config import load_mcp_server_config
from graph_memory_mcp.graph_memory.embedding_service import EmbeddingService

_MODEL = "intfloat/multilingual-e5-base"
_RAW = [
    "The retry policy is three attempts with exponential backoff.",
    "Redis is available at host cache.internal port 6379.",
    "ArcadeDB stores each owner in a separate database.",
    "Write-time deduplication refuses near-duplicate facts.",
    "Search rank mixes cosine similarity, identifiers, and recency.",
    "Background jobs archive stale facts on Sunday at 03:00.",
    "The graph explorer is a local web UI on port 8088.",
    "Token mode sets created_by from the API key name.",
    "Header mode reads the owner from X-Owner-Id.",
    "Changing the embedding model requires a full re-embed.",
    "FalkorDB persists with AOF and fsync every second.",
    "Compact recall returns snippets under a token budget.",
    "CONTRADICTS edges are created by the agent, not inferred.",
    "Политика повторных попыток: три раза с экспоненциальной задержкой.",
    "Redis доступен на хосте cache.internal, порт 6379.",
    "ArcadeDB хранит каждого владельца в отдельной базе.",
    "Дедупликация при записи отклоняет почти одинаковые факты.",
    "Ранжирование поиска смешивает косинус, идентификаторы и свежесть.",
    "Фоновые задачи архивируют устаревшие факты в воскресенье в 03:00.",
    "Проводник графа — локальный веб-интерфейс на порту 8088.",
    "В режиме token поле created_by берётся из имени ключа.",
    "В режиме header владелец читается из заголовка X-Owner-Id.",
    "Смена модели эмбеддингов требует полного пересчёта корпуса.",
    "FalkorDB сохраняет данные через AOF с fsync каждую секунду.",
    "Компактный recall возвращает фрагменты в пределах бюджета токенов.",
]


def _pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for text in _RAW:
        pairs.append((text, "query"))
        pairs.append((text, "passage"))
    return pairs


def _cosine_rows(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    left_n = left / np.linalg.norm(left, axis=1, keepdims=True)
    right_n = right / np.linalg.norm(right, axis=1, keepdims=True)
    return np.sum(left_n * right_n, axis=1)


def _rows(service: EmbeddingService, pairs: list[tuple[str, str]]) -> np.ndarray:
    return np.asarray(
        [service.get_embedding(text, kind=kind) for text, kind in pairs],
        dtype=np.float32,
    )


def test_embedding_backend_config(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BACKEND", "onnx")
    assert load_mcp_server_config().embedding_backend == "onnx"
    monkeypatch.setenv("EMBEDDING_BACKEND", "torch")
    assert load_mcp_server_config().embedding_backend == "torch"


def test_embedding_backend_rejects_unknown(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BACKEND", "quantized")
    with pytest.raises(ValidationError):
        load_mcp_server_config()


def test_unknown_backend_name():
    with pytest.raises(ValueError, match="EMBEDDING_BACKEND"):
        EmbeddingService(model_name=_MODEL, backend="quantized")


@pytest.fixture
def empty_embedding_cache(monkeypatch):
    """Use an empty process-wide model cache, then restore the previous one."""
    from graph_memory_mcp.graph_memory import embedding_backend

    monkeypatch.setattr(embedding_backend, "_LOADED", {})


@pytest.mark.usefixtures("empty_embedding_cache")
def test_torch_backend_missing_extra(monkeypatch):
    real_import = builtins.__import__

    def _import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sentence_transformers" or name.startswith("sentence_transformers."):
            raise ImportError("simulated missing extra")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import)
    with pytest.raises(RuntimeError, match="uv sync --extra torch"):
        EmbeddingService(model_name=_MODEL, backend="torch")


def test_onnx_matches_torch_embeddings():
    pytest.importorskip(
        "sentence_transformers",
        reason="uv sync --extra torch",
    )

    pairs = _pairs()
    assert len(pairs) == 50
    onnx = EmbeddingService(
        model_name=_MODEL,
        query_prefix="query: ",
        passage_prefix="passage: ",
        backend="onnx",
    )
    assert onnx.backend == "onnx"
    assert onnx.dimension == 768
    onnx_single = _rows(onnx, pairs)
    norms = np.linalg.norm(onnx_single, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4)
    assert float(np.abs(onnx_single[0] - onnx_single[1]).sum()) > 0.0

    queries = [text for text, kind in pairs if kind == "query"]
    passages = [text for text, kind in pairs if kind == "passage"]
    batched = np.empty_like(onnx_single)
    batched[0::2] = np.asarray(
        onnx.get_embeddings_batch(queries, kind="query"), dtype=np.float32
    )
    batched[1::2] = np.asarray(
        onnx.get_embeddings_batch(passages, kind="passage"), dtype=np.float32
    )
    single_vs_batch = _cosine_rows(onnx_single, batched)
    assert float(single_vs_batch.min()) >= 0.999

    torch_svc = EmbeddingService(
        model_name=_MODEL,
        query_prefix="query: ",
        passage_prefix="passage: ",
        backend="torch",
    )
    torch_rows = _rows(torch_svc, pairs)
    cosines = _cosine_rows(onnx_single, torch_rows)
    assert float(cosines.min()) >= 0.999
    assert float(cosines.mean()) >= 0.999
