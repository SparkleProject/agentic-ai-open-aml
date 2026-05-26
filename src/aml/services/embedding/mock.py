"""Mock embedding provider for unit tests.

Implements both dense and sparse embedding interfaces so the mock can
be used seamlessly in hybrid-search tests.
"""

import hashlib
import math
import re
import struct

import structlog

logger = structlog.get_logger()


class MockEmbeddingProvider:
    """
    Returns deterministic embeddings derived from the input text hash.

    This is better than random vectors for tests because identical
    inputs always produce identical outputs, making assertions reliable.
    """

    def __init__(self, *, dims: int = 1024) -> None:
        self._dims = dims

    @property
    def dimensions(self) -> int:
        return self._dims

    # ------------------------------------------------------------------
    # Dense embedding (EmbeddingProvider protocol)
    # ------------------------------------------------------------------

    async def embed_text(self, text: str) -> list[float]:
        return self._deterministic_vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._deterministic_vector(t) for t in texts]

    # ------------------------------------------------------------------
    # Sparse embedding (SparseEmbeddingProvider protocol)
    # ------------------------------------------------------------------

    async def embed_sparse(self, text: str) -> dict[int, float]:
        """Generate a deterministic sparse vector from text."""
        return self._deterministic_sparse(text)

    async def embed_sparse_batch(self, texts: list[str]) -> list[dict[int, float]]:
        """Generate deterministic sparse vectors from multiple texts."""
        return [self._deterministic_sparse(t) for t in texts]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _deterministic_vector(self, text: str) -> list[float]:
        """Hash the text and expand to fill ``self._dims`` floats in [-1, 1]."""
        digest = hashlib.sha256(text.encode()).digest()
        # Cycle the 32 bytes to fill the required dimensions
        vector: list[float] = []
        for i in range(self._dims):
            byte_idx = i % len(digest)
            # Convert byte to float in [-1.0, 1.0]
            val = (digest[byte_idx] / 127.5) - 1.0
            # Add a small per-index perturbation so not every 32nd dim is identical
            seed = struct.pack(">I", i)
            perturb = (hashlib.md5(digest + seed, usedforsecurity=False).digest()[0] / 255.0) * 0.01
            vector.append(val + perturb)
        return vector

    @staticmethod
    def _deterministic_sparse(text: str) -> dict[int, float]:
        """Simple token-hash sparse vector for testing."""
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        tokens = [t for t in tokens if len(t) > 1]
        if not tokens:
            return {}
        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        sparse: dict[int, float] = {}
        for term, count in tf.items():
            token_id = int.from_bytes(hashlib.sha256(term.encode()).digest()[:8], "big")
            sparse[token_id] = math.log(1.0 + count)
        return sparse
