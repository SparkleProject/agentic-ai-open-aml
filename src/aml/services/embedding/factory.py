"""Factory for creating the configured embedding provider."""

import structlog

from aml.core.config import Settings
from aml.services.embedding.mock import MockEmbeddingProvider
from aml.services.embedding.ollama import OllamaEmbeddingProvider
from aml.services.embedding.protocol import EmbeddingProvider

logger = structlog.get_logger()


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """
    Instantiate the embedding provider specified by ``settings.embedding_provider``.

    Returns:
        An object satisfying :class:`EmbeddingProvider`.
    """
    name = settings.embedding_provider.lower()

    if name == "ollama":
        return OllamaEmbeddingProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_embedding_model,
            dims=settings.embedding_dimensions,
        )

    if name == "mock":
        return MockEmbeddingProvider(dims=settings.embedding_dimensions)

    if name == "bedrock":
        logger.warning("embedding_provider_not_implemented", provider=name, fallback="mock")
        return MockEmbeddingProvider(dims=settings.embedding_dimensions)

    msg = f"Unknown embedding provider: {name}"
    raise ValueError(msg)
