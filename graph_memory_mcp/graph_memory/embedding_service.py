"""
Embedding service for generating text vector representations.
"""

import logging
from functools import lru_cache
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generate embeddings for text."""

    def __init__(
        self,
        model_name: str,
    ):
        """
        Initialize embedding service.

        Args:
            model_name: SentenceTransformers model name.
        """
        self.model_name = model_name
        logger.info("Loading embedding model: %s", self.model_name)
        self.model = SentenceTransformer(self.model_name)
        test_embedding = self.model.encode("test")
        self.dimension = len(test_embedding)
        logger.info("Model loaded successfully. Dimension: %s", self.dimension)

    def ping(self) -> bool:
        """Check if the embedding service is operational."""
        return self.model is not None and self.dimension > 0

    @lru_cache(maxsize=50000)
    def _get_embedding_cached(self, text: str) -> tuple:
        """
        Internal cached embedding generation.

        Returns a tuple to keep the result hashable for `lru_cache`.

        Args:
            text: input text

        Returns:
            Embedding vector as a tuple of floats.
        """
        embedding = self.model.encode(text)

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

        # Convert to tuple for caching
        return tuple(vec.tolist())

    def get_embedding(self, text: str) -> List[float]:
        """
        Generate an embedding for a single text with LRU caching (maxsize=50000).

        Args:
            text: input text

        Returns:
            Embedding vector as a list of floats.
        """
        return list(self._get_embedding_cached(text))

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a batch of texts.

        Args:
            texts: list of input texts

        Returns:
            List of embedding vectors.
        """
        embeddings = self.model.encode(texts)

        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms > 0, norms, 1)  # Avoid division by zero
        embeddings = embeddings / norms

        # Convert to a list of Python lists
        return [emb.tolist() for emb in embeddings]
