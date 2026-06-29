import json
from typing import Any

import structlog
from pydantic import BaseModel, Field

from aml.core.config import get_settings
from aml.services.llm.factory import get_llm_provider
from aml.services.reporting.narrative import EvidenceBundle, NarrativeDraft

logger = structlog.get_logger()


class VerificationFinding(BaseModel):
    claim: str
    status: str
    source_ref: str | None = None
    suggestion: str | None = None


class VerificationResult(BaseModel):
    findings: list[VerificationFinding] = Field(default_factory=list)

    @property
    def overall_status(self) -> str:
        if any(f.status == "UNVERIFIED" for f in self.findings):
            return "HAS_WARNINGS"
        return "VERIFIED"

    @property
    def unverified_count(self) -> int:
        return sum(1 for f in self.findings if f.status == "UNVERIFIED")

    @property
    def warning_messages(self) -> list[str]:
        return [f"UNVERIFIED: {f.claim} — {f.suggestion}" for f in self.findings if f.status == "UNVERIFIED"]


class NarrativeVerifier:
    def __init__(self, *, llm_provider: Any | None = None) -> None:
        self._llm = llm_provider

    async def verify(
        self,
        *,
        draft: NarrativeDraft,
        evidence: EvidenceBundle,
    ) -> VerificationResult:
        llm = self._resolve_llm()

        narrative_text = "\n\n".join(f"## {name}\n{content}" for name, content in draft.sections.items())
        evidence_text = evidence.format_as_source_blocks()

        prompt = (
            "You are a compliance verification engine. "
            "Cross-reference each factual claim in the narrative against the evidence.\n\n"
            f"## Narrative\n{narrative_text}\n\n"
            f"## Evidence\n{evidence_text}\n\n"
            "For each factual claim, output JSON:\n"
            '{"findings": [{"claim": "...", "status": "VERIFIED"|"UNVERIFIED"|"PARTIALLY_VERIFIED", '
            '"source_ref": "SOURCE-N or null", "suggestion": "fix or null"}]}'
        )

        response = await llm.generate_response(
            prompt=prompt,
            system_prompt="You are a factual verification engine. Be strict. Flag anything unsupported.",
        )

        return self._parse_response(response)

    def apply_result(self, draft: NarrativeDraft, result: VerificationResult) -> NarrativeDraft:
        return NarrativeDraft(
            report_type=draft.report_type,
            case_id=draft.case_id,
            sections=draft.sections,
            citations=draft.citations,
            verification_status=result.overall_status,
            warnings=result.warning_messages,
        )

    def _resolve_llm(self) -> Any:
        if self._llm is not None:
            return self._llm
        settings = get_settings()
        return get_llm_provider(settings)

    @staticmethod
    def _parse_response(response: str) -> VerificationResult:
        try:
            clean = response.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean)
            findings_raw = parsed.get("findings", [])
            findings = [VerificationFinding(**f) for f in findings_raw]
            return VerificationResult(findings=findings)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning("verification_parse_error", error=str(e))
            return VerificationResult(
                findings=[
                    VerificationFinding(
                        claim="Full narrative",
                        status="UNVERIFIED",
                        suggestion=f"Verification failed to parse LLM response: {e}",
                    )
                ]
            )
