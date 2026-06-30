"""Tests for KYC risk scoring engine (BE-302)."""

from aml.db.models.customer import RiskRating
from aml.services.kyc.risk_scoring import RiskScoringEngine


class TestRiskScoringEngine:
    def test_low_risk_individual(self):
        engine = RiskScoringEngine()
        result = engine.calculate_risk(customer_type="individual")

        assert result.overall_score < 30
        assert result.risk_level == RiskRating.LOW
        assert result.auto_decision == "APPROVED"

    def test_high_risk_trust_entity(self):
        engine = RiskScoringEngine()
        result = engine.calculate_risk(customer_type="trust")

        assert result.overall_score > 0
        assert len(result.factor_breakdown) == 5

    def test_pep_hit_raises_score(self):
        engine = RiskScoringEngine()
        result = engine.calculate_risk(
            customer_type="individual",
            pep_result={"is_pep": True, "role": "Head of State"},
        )

        assert result.overall_score >= 20
        pep_factor = next(f for f in result.factor_breakdown if f.factor == "pep_status")
        assert pep_factor.score > 0

    def test_sanctions_match_raises_score(self):
        engine = RiskScoringEngine()
        result = engine.calculate_risk(
            customer_type="individual",
            sanctions_result={"match": True, "lists": ["OFAC"]},
        )

        assert result.overall_score >= 20

    def test_adverse_media_raises_score(self):
        engine = RiskScoringEngine()
        result = engine.calculate_risk(
            customer_type="individual",
            adverse_media_result={"findings": [{"severity": 4, "headline": "Investigation"}]},
        )

        assert result.overall_score > 0

    def test_high_risk_jurisdiction(self):
        engine = RiskScoringEngine()
        result = engine.calculate_risk(customer_type="individual", jurisdiction="KP")

        assert result.overall_score > 0

    def test_multiple_risk_factors_compound(self):
        engine = RiskScoringEngine()
        result = engine.calculate_risk(
            customer_type="trust",
            jurisdiction="IR",
            pep_result={"is_pep": True, "role": "Minister"},
            sanctions_result={"match": True, "lists": ["UN"]},
            adverse_media_result={"findings": [{"severity": 5}]},
        )

        assert result.overall_score >= 70
        assert result.auto_decision in ("REJECTED", "MANUAL_REVIEW")
        assert result.risk_level == RiskRating.HIGH

    def test_custom_tenant_weights(self):
        engine = RiskScoringEngine()
        result_default = engine.calculate_risk(
            customer_type="individual",
            pep_result={"is_pep": True, "role": "Official"},
        )
        result_custom = engine.calculate_risk(
            customer_type="individual",
            pep_result={"is_pep": True, "role": "Official"},
            tenant_weights={"pep_status": 0.50},
        )

        assert result_custom.overall_score > result_default.overall_score

    def test_score_bounded_0_to_100(self):
        engine = RiskScoringEngine()
        result = engine.calculate_risk(
            customer_type="trust",
            jurisdiction="KP",
            pep_result={"is_pep": True},
            sanctions_result={"match": True},
            adverse_media_result={"findings": [{"severity": 5}]},
        )

        assert 0 <= result.overall_score <= 100

    def test_no_data_returns_low_risk(self):
        engine = RiskScoringEngine()
        result = engine.calculate_risk(customer_type="individual")

        assert result.risk_level == RiskRating.LOW
        assert result.auto_decision == "APPROVED"

    def test_manual_review_band(self):
        engine = RiskScoringEngine()
        result = engine.calculate_risk(
            customer_type="trust",
        )

        if 30 <= result.overall_score <= 70:
            assert result.auto_decision == "MANUAL_REVIEW"
