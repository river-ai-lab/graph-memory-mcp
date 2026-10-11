"""
Embedding service for generating text vector representations.
"""

import logging
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generate embeddings for text."""

    def __init__(
        self,
        model_name: str,
        query_prefix: str = "",
        passage_prefix: str = "",
    ):
        """
        Initialize embedding service.

        Args:
            model_name: SentenceTransformers model name.
            query_prefix: prepended to search queries (e5-family: "query: ").
            passage_prefix: prepended to stored texts (e5-family: "passage: ").
        """
        self.model_name = model_name
        self.query_prefix = query_prefix or ""
        self.passage_prefix = passage_prefix or ""
        logger.info("Loading embedding model: %s", self.model_name)
        self.model = SentenceTransformer(self.model_name)
        test_embedding = self.model.encode("test")
        self.dimension = len(test_embedding)
        logger.info("Model loaded successfully. Dimension: %s", self.dimension)

    def _prefix(self, text: str, kind: str) -> str:
        prefix = self.query_prefix if kind == "query" else self.passage_prefix
        return prefix + text

    def ping(self) -> bool:
        """Check if the embedding service is operational."""
        return self.model is not None and self.dimension > 0

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
        embedding = self.model.encode(self._prefix(text, kind))

        # Normalize in numpy space (SentenceTransformers may return torch.Tensor).
        if hasattr(embedding, "detach"):
            embedding = embedding.detach()
        if hasattr(embedding, "cpu"):
            embedding = embedding.cpu()
        if hasattr(embedding, "numpy"):
            embedding = embedding.numpy()

        vec = np.asarray(embedding, dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        if norm > 0.0:
            vec = vec / norm

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
        embeddings = self.model.encode([self._prefix(t, kind) for t in texts])

        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms > 0, norms, 1)  # Avoid division by zero
        embeddings = embeddings / norms

        # Convert to a list of Python lists
        return [emb.tolist() for emb in embeddings]
