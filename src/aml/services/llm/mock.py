"""Mock LLM provider for unit tests."""

from typing import Any, ClassVar

import structlog

logger = structlog.get_logger()


class MockLLMProvider:
    """Returns canned or dynamic smart responses — no network calls."""

    canned_responses: ClassVar[list[str]] = []

    async def generate_response(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,  # noqa: ARG002
        **_kwargs: Any,
    ) -> str:
        logger.debug("mock_llm_generate", prompt_len=len(prompt), system_prompt=system_prompt)

        # 1. Check if there is an explicit override list
        if MockLLMProvider.canned_responses:
            return MockLLMProvider.canned_responses.pop(0)

        # 2. Dynamic heuristic-based mock behavior for Agentic Core execution
        prompt_lower = prompt.lower()

        # Planner node detection
        if "generate a plan" in prompt_lower or "generate a concise text-based" in prompt_lower:
            return "1. Run PEP/Sanctions screening. 2. Fetch transaction history. 3. Synthesize and reflect."

        # Reasoner node detection
        if "decide your next action" in prompt_lower:
            # Check if any tools have already been successfully executed
            if "executed tools history" in prompt_lower and any(
                x in prompt_lower for x in ["sanctionsscreeningtool", "pepscreeningtool", "transactionlookuptool"]
            ):
                # We have executed a tool. Let's conclude!
                import json

                return json.dumps(
                    {
                        "decision": "CONCLUDE",
                        "conclusion": "The customer was screened. No PEP flag raised. Wire normal.",
                    }
                )

            # First turn: Request a screening tool
            import json

            return json.dumps(
                {
                    "decision": "TOOL",
                    "tool_request": {"name": "SanctionsScreeningTool", "parameters": {"entity_name": "bin laden"}},
                }
            )

        # Generic default mock response
        return f"[MOCK] Received: {prompt[:80]}"
