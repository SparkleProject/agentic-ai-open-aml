import json
import logging
import uuid as uuid_mod

from aml.agents.tools.local.adverse_media import AdverseMediaTool
from aml.agents.tools.local.screening import PEPScreeningTool, SanctionsTool
from aml.db.models.cdd_record import CDDRecord, CDDStatus, CDDType
from aml.services.kyc.adapters.mock import MockIdentityVerifier
from aml.services.kyc.protocol import IdentityVerificationProvider
from aml.services.kyc.risk_scoring import RiskScoringEngine

logger = logging.getLogger(__name__)

STAGES = [
    "ID_VERIFICATION",
    "PEP_SCREENING",
    "SANCTIONS_CHECK",
    "ADVERSE_MEDIA",
    "RISK_SCORING",
    "COMPLETE",
]


class CDDPipeline:
    def __init__(
        self,
        *,
        id_verifier: IdentityVerificationProvider | None = None,
        risk_engine: RiskScoringEngine | None = None,
    ) -> None:
        self._id_verifier = id_verifier or MockIdentityVerifier()
        self._risk_engine = risk_engine or RiskScoringEngine()
        self._pep_tool = PEPScreeningTool()
        self._sanctions_tool = SanctionsTool()
        self._adverse_media_tool = AdverseMediaTool()

    async def run_onboarding(
        self,
        *,
        customer_name: str,
        customer_type: str,
        customer_id: str,
        tenant_id: str,
        jurisdiction: str | None = None,
        cdd_type: CDDType = CDDType.INITIAL,
    ) -> CDDRecord:
        record = CDDRecord(
            tenant_id=tenant_id,
            customer_id=uuid_mod.UUID(customer_id) if isinstance(customer_id, str) else customer_id,
            cdd_type=cdd_type,
            status=CDDStatus.IN_PROGRESS,
            onboarding_stage="ID_VERIFICATION",
        )

        try:
            id_result = await self._id_verifier.verify_identity(
                name=customer_name,
                customer_type=customer_type,
            )
            record.id_verification = {
                "verified": id_result.verified,
                "confidence": id_result.confidence,
                "provider_ref": id_result.provider_ref,
            }
            record.onboarding_stage = "PEP_SCREENING"

            pep_raw = await self._pep_tool.execute({"person_name": customer_name})
            record.pep_result = json.loads(pep_raw)
            record.onboarding_stage = "SANCTIONS_CHECK"

            sanctions_raw = await self._sanctions_tool.execute({"entity_name": customer_name})
            record.sanctions_result = json.loads(sanctions_raw)
            record.onboarding_stage = "ADVERSE_MEDIA"

            media_raw = await self._adverse_media_tool.execute({"entity_name": customer_name})
            record.adverse_media_result = json.loads(media_raw)
            record.onboarding_stage = "RISK_SCORING"

            assessment = self._risk_engine.calculate_risk(
                customer_type=customer_type,
                jurisdiction=jurisdiction,
                pep_result=record.pep_result,
                sanctions_result=record.sanctions_result,
                adverse_media_result=record.adverse_media_result,
            )
            record.risk_assessment = {
                "overall_score": assessment.overall_score,
                "risk_level": assessment.risk_level.value,
                "auto_decision": assessment.auto_decision,
                "factors": [
                    {"factor": f.factor, "score": f.score, "weight": f.weight, "explanation": f.explanation}
                    for f in assessment.factor_breakdown
                ],
            }
            record.overall_risk_score = assessment.overall_score
            record.decision = assessment.auto_decision
            record.onboarding_stage = "COMPLETE"

            if assessment.auto_decision == "MANUAL_REVIEW" or assessment.auto_decision == "REJECTED":
                record.status = CDDStatus.ESCALATED
            else:
                record.status = CDDStatus.COMPLETE

        except Exception as e:
            logger.exception("CDD pipeline failed")
            record.status = CDDStatus.FAILED
            record.decision = f"FAILED: {e}"

        return record
