"""
Protocol for embedding providers.

Embedding is separate from LLM chat so you can use different backends
for each (e.g. Ollama for embeddings, Azure for chat).
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
        """Embed a single string into a vector."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple strings into vectors."""
        ...
