"""
Protocol for LLM (chat-completion) providers.

Every LLM backend must satisfy this interface so callers never depend
on a concrete implementation.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Interface that all LLM providers must implement."""

    async def generate_response(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> str:
        """
        Generate a text response from the model.

        Args:
            prompt: The user message.
            system_prompt: Optional system instruction.
            history: Prior conversation turns `[{"role": "user"|"assistant", "content": "..."}]`.
            **kwargs: Provider-specific overrides (temperature, max_tokens, etc.).
        """
        ...
