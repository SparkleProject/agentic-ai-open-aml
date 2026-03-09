"""
Integration test — Ollama embeddings with mxbai-embed-large.

Requires: ollama running locally with mxbai-embed-large pulled.
Run: pytest tests/test_embedding_ollama.py -v -m integration
"""

import pytest

from aml.core.config import Settings
from aml.services.embedding.factory import get_embedding_provider

pytestmark = pytest.mark.integration


class TestOllamaEmbeddingIntegration:
    async def test_embed_single_text(self):
        settings = Settings(embedding_provider="ollama", _env_file=None)
        provider = get_embedding_provider(settings)

        vec = await provider.embed_text("AML transaction monitoring alert")
        assert isinstance(vec, list)
        assert len(vec) == settings.embedding_dimensions
        assert all(isinstance(v, float) for v in vec)

    async def test_embed_batch(self):
        settings = Settings(embedding_provider="ollama", _env_file=None)
        provider = get_embedding_provider(settings)

        texts = [
            "Suspicious wire transfer to shell company",
            "Customer due diligence check for high-risk PEP",
            "Structuring transactions below reporting threshold",
        ]
        vecs = await provider.embed_batch(texts)
        assert len(vecs) == 3
        assert all(len(v) == settings.embedding_dimensions for v in vecs)

    async def test_different_texts_different_vectors(self):
        settings = Settings(embedding_provider="ollama", _env_file=None)
        provider = get_embedding_provider(settings)

        vec_a = await provider.embed_text("money laundering")
        vec_b = await provider.embed_text("legitimate business transaction")
        assert vec_a != vec_b
