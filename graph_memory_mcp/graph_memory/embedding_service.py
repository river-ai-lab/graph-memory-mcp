"""
Embedding service for generating text vector representations.

The default backend is ONNX Runtime (fp32 weights). ``backend="torch"`` uses
sentence-transformers when the optional ``torch`` extra is installed.
"""

from __future__ import annotations

import logging
from typing import List

import numpy as np

from graph_memory_mcp.graph_memory.embedding_backend import load_embedding_backend

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generate embeddings for text."""

    def __init__(
        self,
        model_name: str,
        query_prefix: str = "",
        passage_prefix: str = "",
        backend: str = "onnx",
    ):
        """
        Initialize embedding service.

        Args:
            model_name: Hugging Face model id (default ``intfloat/multilingual-e5-base``).
            query_prefix: prepended to search queries (e5-family: "query: ").
            passage_prefix: prepended to stored texts (e5-family: "passage: ").
            backend: ``onnx`` (default) or ``torch``.
        """
        self.model_name = model_name
        self.backend = (backend or "onnx").strip().lower()
        self.query_prefix = query_prefix or ""
        self.passage_prefix = passage_prefix or ""
        logger.info(
            "Loading embedding model: %s (backend=%s)",
            self.model_name,
            self.backend,
        )
        self._backend = load_embedding_backend(self.backend, self.model_name)
        probe = self._backend.encode(["test"])
        self.dimension = int(probe.shape[-1])
        logger.info("Model loaded successfully. Dimension: %s", self.dimension)

    def _prefix(self, text: str, kind: str) -> str:
        prefix = self.query_prefix if kind == "query" else self.passage_prefix
        return prefix + text

    def ping(self) -> bool:
        """Check if the embedding service is operational."""
        return self._backend is not None and self.dimension > 0

    def _normalize(self, embeddings: np.ndarray) -> np.ndarray:
        vecs = np.asarray(embeddings, dtype=np.float32)
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        if vecs.size == 0:
            return vecs
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms = np.where(norms > 0, norms, 1.0)
        return vecs / norms

    def get_embedding(self, text: str, kind: str = "passage") -> List[float]:
        """
        Generate a normalized embedding for a single text.

        Caching is handled by the caller (`FalkorDBClient` via `CacheManager`).

        Args:
            text: input text
            kind: "passage" for stored texts, "query" for search queries

        Returns:
            Embedding vector as a list of floats.
        """
        vec = self._normalize(self._backend.encode([self._prefix(text, kind)]))[0]
        return [float(v) for v in vec.tolist()]

    def get_embeddings_batch(
        self, texts: List[str], kind: str = "passage"
    ) -> List[List[float]]:
        """
        Generate embeddings for a batch of texts.

        Args:
            texts: list of input texts
            kind: "passage" for stored texts, "query" for search queries

        Returns:
            List of embedding vectors.
        """
        if not texts:
            return []
        rows = self._normalize(
            self._backend.encode([self._prefix(text, kind) for text in texts])
        )
        return [row.tolist() for row in rows]
