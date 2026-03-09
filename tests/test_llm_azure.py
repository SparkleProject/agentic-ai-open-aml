"""
Integration test — Azure OpenAI chat completions.

Requires AML_LLM_PROVIDER=azure and valid Azure credentials in .env.
Run: pytest tests/test_llm_azure.py -v -m integration
"""

import pytest

from aml.core.config import Settings
from aml.services.llm.factory import get_llm_provider

pytestmark = pytest.mark.integration


class TestAzureOpenAIIntegration:
    async def test_chat_completion(self):
        settings = Settings()  # reads .env
        if settings.llm_provider.lower() != "azure":
            pytest.skip("AML_LLM_PROVIDER is not 'azure'")

        provider = get_llm_provider(settings)
        response = await provider.generate_response(
            "Respond with exactly: PONG",
            system_prompt="You are a connectivity test bot. Follow instructions exactly.",
        )
        assert isinstance(response, str)
        assert len(response) > 0
