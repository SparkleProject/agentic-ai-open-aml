"""Unit tests for LLM and Embedding providers (no external services)."""

import pytest

from aml.core.config import Settings
from aml.services.embedding.factory import get_embedding_provider
from aml.services.embedding.mock import MockEmbeddingProvider
from aml.services.embedding.protocol import EmbeddingProvider
from aml.services.llm.factory import get_llm_provider
from aml.services.llm.mock import MockLLMProvider
from aml.services.llm.protocol import LLMProvider

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


class TestMockLLM:
    async def test_mock_satisfies_protocol(self):
        provider = MockLLMProvider()
        assert isinstance(provider, LLMProvider)

    async def test_mock_returns_string(self):
        provider = MockLLMProvider()
        result = await provider.generate_response("hello")
        assert isinstance(result, str)
        assert "hello" in result

    async def test_factory_returns_mock(self):
        settings = Settings(llm_provider="mock", _env_file=None)
        provider = get_llm_provider(settings)
        assert isinstance(provider, MockLLMProvider)

    async def test_factory_rejects_unknown(self):
        settings = Settings(llm_provider="unknown_provider", _env_file=None)
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_llm_provider(settings)

    async def test_factory_azure_requires_config(self):
        settings = Settings(llm_provider="azure", _env_file=None)
        with pytest.raises(ValueError, match="Azure OpenAI requires"):
            get_llm_provider(settings)


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


class TestMockEmbedding:
    async def test_mock_satisfies_protocol(self):
        provider = MockEmbeddingProvider(dims=1024)
        assert isinstance(provider, EmbeddingProvider)

    async def test_mock_dimensions(self):
        provider = MockEmbeddingProvider(dims=1024)
        assert provider.dimensions == 1024

    async def test_mock_embed_text_returns_correct_dims(self):
        provider = MockEmbeddingProvider(dims=1024)
        vec = await provider.embed_text("hello world")
        assert len(vec) == 1024
        assert all(isinstance(v, float) for v in vec)

    async def test_mock_deterministic(self):
        provider = MockEmbeddingProvider(dims=1024)
        vec_a = await provider.embed_text("same input")
        vec_b = await provider.embed_text("same input")
        assert vec_a == vec_b

    async def test_mock_different_inputs_differ(self):
        provider = MockEmbeddingProvider(dims=1024)
        vec_a = await provider.embed_text("input A")
        vec_b = await provider.embed_text("input B")
        assert vec_a != vec_b

    async def test_mock_batch(self):
        provider = MockEmbeddingProvider(dims=1024)
        vecs = await provider.embed_batch(["one", "two", "three"])
        assert len(vecs) == 3
        assert all(len(v) == 1024 for v in vecs)

    async def test_factory_returns_mock(self):
        settings = Settings(embedding_provider="mock", _env_file=None)
        provider = get_embedding_provider(settings)
        assert isinstance(provider, MockEmbeddingProvider)

    async def test_factory_rejects_unknown(self):
        settings = Settings(embedding_provider="unknown_provider", _env_file=None)
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            get_embedding_provider(settings)
