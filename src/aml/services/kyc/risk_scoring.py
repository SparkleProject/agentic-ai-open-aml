from dataclasses import dataclass, field
from typing import Any

from aml.db.models.customer import RiskRating

DEFAULT_WEIGHTS: dict[str, float] = {
    "customer_type": 0.30,
    "pep_status": 0.25,
    "sanctions": 0.20,
    "adverse_media": 0.15,
    "transaction_profile": 0.10,
}

HIGH_RISK_ENTITY_TYPES = {"trust", "partnership", "offshore"}
HIGH_RISK_JURISDICTIONS = {"IR", "KP", "SY", "CU", "MM"}


@dataclass
class FactorScore:
    factor: str
    score: float
    weight: float
    explanation: str


@dataclass
class RiskAssessment:
    overall_score: int
    risk_level: RiskRating
    auto_decision: str
    factor_breakdown: list[FactorScore] = field(default_factory=list)


class RiskScoringEngine:
    def calculate_risk(
        self,
        *,
        customer_type: str,
        jurisdiction: str | None = None,
        pep_result: dict[str, Any] | None = None,
        sanctions_result: dict[str, Any] | None = None,
        adverse_media_result: dict[str, Any] | None = None,
        tenant_weights: dict[str, float] | None = None,
    ) -> RiskAssessment:
        weights = {**DEFAULT_WEIGHTS, **(tenant_weights or {})}
        factors: list[FactorScore] = []

        ct_score = self._score_customer_type(customer_type, jurisdiction)
        factors.append(FactorScore("customer_type", ct_score, weights["customer_type"], f"Type: {customer_type}"))

        pep_score = self._score_pep(pep_result)
        factors.append(FactorScore("pep_status", pep_score, weights["pep_status"], self._pep_explanation(pep_result)))

        sanc_score = self._score_sanctions(sanctions_result)
        sanc_explanation = self._sanctions_explanation(sanctions_result)
        factors.append(FactorScore("sanctions", sanc_score, weights["sanctions"], sanc_explanation))

        media_score = self._score_adverse_media(adverse_media_result)
        factors.append(FactorScore("adverse_media", media_score, weights["adverse_media"], "Media scan result"))

        factors.append(FactorScore("transaction_profile", 0.0, weights["transaction_profile"], "No history yet"))

        raw = sum(f.score * f.weight for f in factors)
        overall = min(max(int(raw), 0), 100)

        return RiskAssessment(
            overall_score=overall,
            risk_level=self._score_to_rating(overall),
            auto_decision=self._score_to_decision(overall),
            factor_breakdown=factors,
        )

    @staticmethod
    def _score_customer_type(customer_type: str, jurisdiction: str | None) -> float:
        score = 0.0
        if customer_type.lower() in HIGH_RISK_ENTITY_TYPES:
            score += 60.0
        if jurisdiction and jurisdiction.upper() in HIGH_RISK_JURISDICTIONS:
            score += 40.0
        return min(score, 100.0)

    @staticmethod
    def _score_pep(result: dict[str, Any] | None) -> float:
        if not result:
            return 0.0
        if result.get("is_pep"):
            return 90.0
        return 0.0

    @staticmethod
    def _score_sanctions(result: dict[str, Any] | None) -> float:
        if not result:
            return 0.0
        if result.get("match"):
            return 100.0
        return 0.0

    @staticmethod
    def _score_adverse_media(result: dict[str, Any] | None) -> float:
        if not result:
            return 0.0
        findings = result.get("findings", [])
        if not findings:
            return 0.0
        max_severity = max(f.get("severity", 0) for f in findings)
        return min(float(max_severity) * 20.0, 100.0)

    @staticmethod
    def _pep_explanation(result: dict[str, Any] | None) -> str:
        if not result:
            return "No PEP data"
        if result.get("is_pep"):
            return f"PEP: {result.get('role', 'unknown role')}"
        return "Not a PEP"

    @staticmethod
    def _sanctions_explanation(result: dict[str, Any] | None) -> str:
        if not result:
            return "No sanctions data"
        if result.get("match"):
            return f"Sanctions match: {result.get('lists', [])}"
        return "No sanctions match"

    @staticmethod
    def _score_to_rating(score: int) -> RiskRating:
        if score >= 70:
            return RiskRating.HIGH
        if score >= 30:
            return RiskRating.MEDIUM
        return RiskRating.LOW

    @staticmethod
    def _score_to_decision(score: int) -> str:
        if score < 30:
            return "APPROVED"
        if score <= 70:
            return "MANUAL_REVIEW"
        return "REJECTED"
