import json
from abc import ABC, abstractmethod
from typing import Any

import structlog
from pydantic import BaseModel, Field

from aml.core.config import get_settings
from aml.services.llm.factory import get_llm_provider
from aml.services.reporting.templates import TemplateRegistry

logger = structlog.get_logger()


class EvidenceBundle(BaseModel):
    case_id: str
    alert_details: dict[str, Any]
    investigation_reasoning: dict[str, Any]
    customer_profile: dict[str, Any]
    transactions: list[dict[str, Any]]

    def format_as_source_blocks(self) -> str:
        blocks: list[str] = []
        source_num = 1

        if self.customer_profile:
            blocks.append(f"[SOURCE-{source_num}: Customer Profile]\n{json.dumps(self.customer_profile, indent=2)}")
            source_num += 1

        if self.alert_details:
            blocks.append(f"[SOURCE-{source_num}: Alert]\n{json.dumps(self.alert_details, indent=2)}")
            source_num += 1

        for tx in self.transactions:
            tx_id = tx.get("id", f"TX-{source_num}")
            blocks.append(f"[SOURCE-{source_num}: Transaction {tx_id}]\n{json.dumps(tx, indent=2)}")
            source_num += 1

        if self.investigation_reasoning:
            blocks.append(
                f"[SOURCE-{source_num}: Investigation Reasoning]\n{json.dumps(self.investigation_reasoning, indent=2)}"
            )

        return "\n\n".join(blocks)


class NarrativeDraft(BaseModel):
    report_type: str
    case_id: str
    sections: dict[str, str] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    verification_status: str = "PENDING"
    warnings: list[str] = Field(default_factory=list)

    def missing_sections(self, required: list[str]) -> list[str]:
        return [name for name in required if name not in self.sections]


class NarrativeGenerator(ABC):
    @abstractmethod
    async def generate_draft(
        self,
        *,
        evidence: EvidenceBundle,
        report_type: str,
        tenant_id: str,
    ) -> NarrativeDraft: ...


class NarrativeGenerationService(NarrativeGenerator):
    def __init__(
        self,
        *,
        template_registry: TemplateRegistry | None = None,
        llm_provider: Any | None = None,
    ) -> None:
        self._templates = template_registry or TemplateRegistry()
        self._llm = llm_provider

    async def generate_draft(
        self,
        *,
        evidence: EvidenceBundle,
        report_type: str,
        tenant_id: str,  # noqa: ARG002
    ) -> NarrativeDraft:
        template = self._templates.get_template(report_type)
        llm = self._resolve_llm()

        source_blocks = evidence.format_as_source_blocks()
        section_instructions = self._build_section_instructions(template)

        prompt = (
            f"Generate a regulatory report with the following sections.\n\n"
            f"## Required Sections\n{section_instructions}\n\n"
            f"## Evidence\n{source_blocks}\n\n"
            f"Output strictly valid JSON mapping section names to their content. "
            f"Cite evidence using [SOURCE-N] references."
        )

        response = await llm.generate_response(
            prompt=prompt,
            system_prompt=template.system_prompt_addendum,
        )

        return self._parse_response(response, report_type, evidence.case_id)

    def _resolve_llm(self) -> Any:
        if self._llm is not None:
            return self._llm
        settings = get_settings()
        return get_llm_provider(settings)

    @staticmethod
    def _build_section_instructions(template: Any) -> str:
        lines: list[str] = []
        for section in template.sections:
            req = "REQUIRED" if section.required else "OPTIONAL"
            lines.append(f"- **{section.name}** ({req}, max {section.max_words} words): {section.guidance}")
        return "\n".join(lines)

    @staticmethod
    def _parse_response(response: str, report_type: str, case_id: str) -> NarrativeDraft:
        warnings: list[str] = []
        sections: dict[str, str] = {}

        try:
            clean = response.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean)
            if isinstance(parsed, dict):
                sections = {k: str(v) for k, v in parsed.items()}
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("narrative_parse_error", error=str(e))
            warnings.append(f"Failed to parse LLM response as JSON: {e}")
            sections = {"raw_response": response}

        return NarrativeDraft(
            report_type=report_type,
            case_id=case_id,
            sections=sections,
            verification_status="PENDING",
            warnings=warnings,
        )
