"""Shared embedding lookup for Falkor and Arcade clients.

Cache key is ``{kind}:{text}``. A service that does not accept ``kind`` is
called without it. A failed lookup returns an empty vector and does not
raise.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def attach_embedding_service(client: Any, service: Any) -> None:
    """Attach an embedding service and log its dimension."""
    client._embedding_service = service
    logger.info(
        "Embedding service attached (dimension=%s)",
        getattr(service, "dimension", 0),
    )


def cached_embedding(client: Any, text: str, kind: str = "passage") -> list[float]:
    """Return one embedding, using the client's LRU cache."""
    if client._embedding_service is None:
        logger.warning("Embedding service not available")
        return []
    cache_key = f"{kind}:{text}"
    cached = client.cache.get_embedding(cache_key)
    if cached is not None:
        return cached
    try:
        embedding = client._embedding_service.get_embedding(text, kind=kind)
    except TypeError:
        embedding = client._embedding_service.get_embedding(text)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to get embedding: %s", exc)
        return []
    if embedding:
        client.cache.set_embedding(cache_key, embedding)
    return embedding


def cached_embeddings_batch(
    client: Any, texts: list[str], kind: str = "passage"
) -> list[list[float]]:
    """Return embeddings for a batch. A failure yields one empty vector each."""
    if client._embedding_service is None:
        logger.warning("Embedding service not available")
        return [[] for _ in texts]
    try:
        return client._embedding_service.get_embeddings_batch(texts, kind=kind)
    except TypeError:
        return client._embedding_service.get_embeddings_batch(texts)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to get batch embeddings: %s", exc)
        return [[] for _ in texts]
