"""
Azure OpenAI LLM provider.

Uses the official ``openai`` library's async Azure client for chat completions.
"""

from typing import Any

import structlog
from openai import AsyncAzureOpenAI

logger = structlog.get_logger()


class AzureOpenAIProvider:
    """Chat-completion provider backed by Azure OpenAI Service."""

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        deployment_name: str,
        api_version: str = "2024-08-01-preview",
        reasoning_effort: str = "low",
    ) -> None:
        # Normalise the endpoint — the openai library appends /openai/deployments/…
        clean = endpoint.rstrip("/")
        if clean.endswith("/openai/v1"):
            clean = clean[:-10].rstrip("/")
        elif clean.endswith("/openai"):
            clean = clean[:-7].rstrip("/")

        self._deployment = deployment_name
        self._reasoning_effort = reasoning_effort
        self._client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=clean,
            api_version=api_version,
        )
        logger.info(
            "azure_openai_provider_init",
            endpoint=clean,
            deployment=deployment_name,
            reasoning_effort=reasoning_effort,
        )

    async def generate_response(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> str:
        """Call the Azure OpenAI chat-completions endpoint."""
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        if "reasoning_effort" not in kwargs:
            kwargs["reasoning_effort"] = self._reasoning_effort

        resp = await self._client.chat.completions.create(
            model=self._deployment,
            messages=messages,
            **kwargs,
        )
        return resp.choices[0].message.content or ""
