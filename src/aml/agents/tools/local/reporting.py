import json
from typing import Any

from pydantic import BaseModel, Field

from aml.agents.tools.protocol import BaseTool
from aml.services.reporting.narrative import (
    EvidenceBundle,
    NarrativeGenerationService,
)
from aml.services.reporting.templates import TemplateRegistry


class NarrativeDraftInput(BaseModel):
    case_id: str = Field(description="The case ID to generate a narrative for.")
    report_type: str = Field(description="Report type, e.g. AUSTRAC_SMR, NZ_SAR.")


class NarrativeDraftTool(BaseTool):
    @property
    def name(self) -> str:
        return "NarrativeDraftTool"

    @property
    def description(self) -> str:
        return (
            "Generates a draft regulatory report narrative for a given case. "
            "Supports AUSTRAC SMR, TTR, IFTI, and NZ SAR formats."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return NarrativeDraftInput.model_json_schema()

    async def execute(self, params: dict[str, Any]) -> str:
        try:
            validated = NarrativeDraftInput(**params)
        except Exception as e:
            return f"Error: invalid parameters — {e}"

        evidence = EvidenceBundle(
            case_id=validated.case_id,
            alert_details={},
            investigation_reasoning={},
            customer_profile={},
            transactions=[],
        )

        registry = TemplateRegistry()
        try:
            registry.get_template(validated.report_type)
        except KeyError:
            return f"Error: unknown report type '{validated.report_type}'"

        service = NarrativeGenerationService(template_registry=registry)
        draft = await service.generate_draft(
            evidence=evidence,
            report_type=validated.report_type,
            tenant_id="agent-context",
        )

        return json.dumps(
            {
                "report_type": draft.report_type,
                "case_id": draft.case_id,
                "sections": draft.sections,
                "verification_status": draft.verification_status,
                "warnings": draft.warnings,
            }
        )
