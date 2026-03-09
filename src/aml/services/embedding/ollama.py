"""
Ollama embedding provider.

Calls the Ollama REST API (``/api/embed``) using ``httpx`` — no extra
dependencies beyond what's already in the project.

Default model: ``mxbai-embed-large`` (1024 dimensions).
"""

import httpx
import structlog

logger = structlog.get_logger()


class OllamaEmbeddingProvider:
    """Embedding provider backed by a local Ollama instance."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "mxbai-embed-large",
        dims: int = 1024,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dims = dims
        self._timeout = timeout
        logger.info(
            "ollama_embedding_provider_init",
            base_url=self._base_url,
            model=self._model,
            dimensions=self._dims,
        )

    @property
    def dimensions(self) -> int:
        return self._dims

    async def embed_text(self, text: str) -> list[float]:
        """Embed a single string."""
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed multiple strings in one call.

        Ollama's ``/api/embed`` accepts ``input`` as a list of strings
        and returns ``embeddings`` as a list of float-lists.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()

        embeddings: list[list[float]] = data["embeddings"]

        if embeddings and len(embeddings[0]) != self._dims:
            logger.warning(
                "embedding_dim_mismatch",
                expected=self._dims,
                actual=len(embeddings[0]),
                model=self._model,
            )

        return embeddings
