"""Factory for creating the configured LLM provider."""

import structlog

from aml.core.config import Settings
from aml.services.llm.azure_openai import AzureOpenAIProvider
from aml.services.llm.mock import MockLLMProvider
from aml.services.llm.protocol import LLMProvider

logger = structlog.get_logger()


def get_llm_provider(settings: Settings) -> LLMProvider:
    """
    Instantiate the LLM provider specified by ``settings.llm_provider``.

    Returns:
        An object satisfying :class:`LLMProvider`.
    """
    name = settings.llm_provider.lower()

    if name == "azure":
        required = [
            settings.azure_openai_api_key,
            settings.azure_openai_endpoint,
            settings.azure_openai_deployment_name,
        ]
        if not all(required):
            msg = "Azure OpenAI requires AML_AZURE_OPENAI_{API_KEY,ENDPOINT,DEPLOYMENT_NAME}"
            raise ValueError(msg)
        return AzureOpenAIProvider(
            api_key=settings.azure_openai_api_key,  # type: ignore[arg-type]
            endpoint=settings.azure_openai_endpoint,  # type: ignore[arg-type]
            deployment_name=settings.azure_openai_deployment_name,  # type: ignore[arg-type]
            api_version=settings.azure_openai_api_version,
            reasoning_effort=settings.azure_openai_reasoning_effort,
        )

    if name == "mock":
        return MockLLMProvider()

    if name in ("bedrock", "ollama"):
        logger.warning("llm_provider_not_implemented", provider=name, fallback="mock")
        return MockLLMProvider()

    msg = f"Unknown LLM provider: {name}"
    raise ValueError(msg)
