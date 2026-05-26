"""
Protocol for embedding providers.

Embedding is separate from LLM chat so you can use different backends
for each (e.g. Ollama for embeddings, Azure for chat).

Dense embeddings capture semantic meaning; sparse embeddings (BM25 / SPLADE)
capture exact keyword matches.  Both are needed for hybrid search.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Interface that all embedding providers must implement."""

    @property
    def dimensions(self) -> int:
        """Number of dimensions in the output vectors."""
        ...

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single string into a dense vector."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple strings into dense vectors."""
        ...


@runtime_checkable
class SparseEmbeddingProvider(Protocol):
    """Interface for sparse (BM25 / SPLADE) embedding providers.

    Sparse embeddings are represented as dictionaries mapping integer
    token IDs to their float importance weights.  These power the
    exact-keyword leg of hybrid search.
    """

    async def embed_sparse(self, text: str) -> dict[int, float]:
        """Generate a sparse vector for a single string."""
        ...

    async def embed_sparse_batch(self, texts: list[str]) -> list[dict[int, float]]:
        """Generate sparse vectors for multiple strings."""
        ...
