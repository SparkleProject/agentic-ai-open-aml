from typing import Any

import structlog

from aml.services.guardrails.input_validator import InputValidator
from aml.services.guardrails.output_validator import OutputValidator
from aml.services.guardrails.pii_redactor import PIIRedactor

logger = structlog.get_logger()


class GuardedLLMProvider:
    def __init__(
        self,
        *,
        provider: Any,
        input_validator: InputValidator | None = None,
        output_validator: OutputValidator | None = None,
        pii_redactor: PIIRedactor | None = None,
    ) -> None:
        self._provider = provider
        self._input_validator = input_validator or InputValidator()
        self._output_validator = output_validator or OutputValidator()
        self._pii_redactor = pii_redactor or PIIRedactor()

    async def generate_response(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> str:
        input_result = self._input_validator.validate(prompt, system_prompt)

        if not input_result.is_safe:
            logger.warning(
                "guardrail_input_blocked",
                reason=input_result.blocked_reason,
                patterns=input_result.matched_patterns,
            )
            return f"[BLOCKED] Input rejected: {input_result.blocked_reason}"

        response = await self._provider.generate_response(
            input_result.sanitised_input,
            system_prompt=system_prompt,
            history=history,
            **kwargs,
        )

        output_result = self._output_validator.validate(response)
        if not output_result.is_safe:
            logger.warning(
                "guardrail_output_flagged",
                reason=output_result.flagged_reason,
                patterns=output_result.matched_patterns,
            )

        redacted = self._pii_redactor.redact(response)
        if redacted.pii_found:
            logger.info(
                "guardrail_pii_redacted",
                redaction_count=len(redacted.redactions),
                types=[r.pii_type for r in redacted.redactions],
            )

        return response
