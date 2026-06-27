import json

import structlog
from pydantic import BaseModel, Field

from aml.core.config import get_settings
from aml.db.models.alert import Alert
from aml.services.llm.factory import get_llm_provider
from aml.services.rag.service import RAGService

logger = structlog.get_logger()


class TriageResult(BaseModel):
    score: int = Field(..., ge=0, le=100, description="Risk score from 0 to 100")
    decision: str = Field(..., description="'AUTO_CLEAR' or 'INVESTIGATE'")
    rationale: str = Field(..., description="Explanation for the decision")


class AlertTriageService:
    def __init__(self, rag_service: RAGService | None = None):
        self.rag_service = rag_service

    async def triage_alert(self, alert: Alert) -> TriageResult:
        settings = get_settings()
        llm = get_llm_provider(settings)

        context = ""
        if self.rag_service:
            query = f"Alert Type: {alert.alert_type}. {alert.title}. {alert.description}"
            results = await self.rag_service.query(question=query, tenant_id=alert.tenant_id, limit=3)
            context = self.rag_service.format_context(results)

        system_prompt = (
            "You are an expert AML alert triage engine. "
            "Your job is to read an alert and determine if it is a low-risk false positive "
            "that can be auto-cleared, or if it requires full investigation.\n"
            "Output strictly valid JSON matching the schema:\n"
            "{\n"
            '  "score": int (0-100),\n'
            '  "decision": "AUTO_CLEAR" or "INVESTIGATE",\n'
            '  "rationale": "string"\n'
            "}"
        )

        prompt = f"""
        Alert ID: {alert.id}
        Type: {alert.alert_type}
        Severity: {alert.severity}
        Title: {alert.title}
        Description: {alert.description}

        Relevant Policy Context:
        {context}

        Evaluate this alert. If score < 20, you MUST return AUTO_CLEAR. Otherwise INVESTIGATE.
        """

        response_text = await llm.generate_response(prompt=prompt, system_prompt=system_prompt, temperature=0.1)

        try:
            clean_json = response_text.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            return TriageResult(**data)
        except Exception as e:
            logger.error("triage_json_parse_error", error=str(e), response=response_text)
            return TriageResult(score=100, decision="INVESTIGATE", rationale=f"Failed to parse LLM response: {e}")
