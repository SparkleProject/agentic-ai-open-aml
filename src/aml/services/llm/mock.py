"""Mock LLM provider for unit tests."""

from typing import Any

import structlog

logger = structlog.get_logger()


class MockLLMProvider:
    """Returns canned responses — no network calls."""

    async def generate_response(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,  # noqa: ARG002
        history: list[dict[str, str]] | None = None,  # noqa: ARG002
        **_kwargs: Any,
    ) -> str:
        logger.debug("mock_llm_generate", prompt_len=len(prompt))
        return f"[MOCK] Received: {prompt[:80]}"
