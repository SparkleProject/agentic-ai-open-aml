"""Tests for Chain of Verification (BE-301 Step 3)."""

import json
import uuid

import pytest

from aml.services.llm.mock import MockLLMProvider
from aml.services.reporting.narrative import EvidenceBundle, NarrativeDraft
from aml.services.reporting.verification import (
    NarrativeVerifier,
    VerificationFinding,
    VerificationResult,
)


@pytest.fixture
def sample_draft():
    return NarrativeDraft(
        report_type="AUSTRAC_SMR",
        case_id=str(uuid.uuid4()),
        sections={
            "Subject Details": "John Smith, DOB 1985-03-15, account 123456.",
            "Suspicious Activity Description": "12 deposits of $9,900 within 48 hours [SOURCE-1].",
            "Transaction Details": "TXN-001: $9,900 on 2026-06-01 [SOURCE-2].",
            "Reason for Suspicion": "Structuring under AML/CTF Act s.41.",
        },
        verification_status="PENDING",
    )


@pytest.fixture
def sample_evidence():
    return EvidenceBundle(
        case_id=str(uuid.uuid4()),
        alert_details={"title": "Structuring detected"},
        investigation_reasoning={"conclusion": "Structuring confirmed"},
        customer_profile={"name": "John Smith", "dob": "1985-03-15"},
        transactions=[
            {"id": "TXN-001", "amount": 9900, "date": "2026-06-01"},
        ],
    )


class TestVerificationFinding:
    def test_creation(self):
        finding = VerificationFinding(
            claim="12 deposits of $9,900",
            status="VERIFIED",
            source_ref="SOURCE-1",
        )
        assert finding.status == "VERIFIED"
        assert finding.source_ref == "SOURCE-1"
        assert finding.suggestion is None

    def test_unverified_with_suggestion(self):
        finding = VerificationFinding(
            claim="Customer has criminal history",
            status="UNVERIFIED",
            suggestion="Remove — no evidence supports this claim.",
        )
        assert finding.status == "UNVERIFIED"
        assert finding.suggestion is not None


class TestVerificationResult:
    def test_all_verified(self):
        result = VerificationResult(
            findings=[
                VerificationFinding(claim="Fact A", status="VERIFIED", source_ref="SOURCE-1"),
                VerificationFinding(claim="Fact B", status="VERIFIED", source_ref="SOURCE-2"),
            ],
        )
        assert result.overall_status == "VERIFIED"
        assert result.unverified_count == 0

    def test_has_unverified(self):
        result = VerificationResult(
            findings=[
                VerificationFinding(claim="Fact A", status="VERIFIED", source_ref="SOURCE-1"),
                VerificationFinding(claim="Bad claim", status="UNVERIFIED", suggestion="Remove it."),
            ],
        )
        assert result.overall_status == "HAS_WARNINGS"
        assert result.unverified_count == 1
        assert result.warning_messages == ["UNVERIFIED: Bad claim — Remove it."]

    def test_empty_findings(self):
        result = VerificationResult(findings=[])
        assert result.overall_status == "VERIFIED"
        assert result.unverified_count == 0


class TestNarrativeVerifier:
    async def test_verify_all_claims_supported(self, sample_draft, sample_evidence):
        MockLLMProvider.canned_responses = [
            json.dumps(
                {
                    "findings": [
                        {"claim": "John Smith, DOB 1985-03-15", "status": "VERIFIED", "source_ref": "SOURCE-1"},
                        {"claim": "12 deposits of $9,900", "status": "VERIFIED", "source_ref": "SOURCE-2"},
                    ]
                }
            )
        ]

        verifier = NarrativeVerifier()
        result = await verifier.verify(draft=sample_draft, evidence=sample_evidence)

        assert isinstance(result, VerificationResult)
        assert result.overall_status == "VERIFIED"

    async def test_verify_catches_hallucination(self, sample_draft, sample_evidence):
        MockLLMProvider.canned_responses = [
            json.dumps(
                {
                    "findings": [
                        {"claim": "John Smith, DOB 1985-03-15", "status": "VERIFIED", "source_ref": "SOURCE-1"},
                        {
                            "claim": "Customer has known ties to organized crime",
                            "status": "UNVERIFIED",
                            "suggestion": "Remove — no evidence in the case file supports this.",
                        },
                    ]
                }
            )
        ]

        verifier = NarrativeVerifier()
        result = await verifier.verify(draft=sample_draft, evidence=sample_evidence)

        assert result.overall_status == "HAS_WARNINGS"
        assert result.unverified_count == 1

    async def test_verify_updates_draft(self, sample_draft, sample_evidence):
        MockLLMProvider.canned_responses = [
            json.dumps(
                {
                    "findings": [
                        {"claim": "Some fact", "status": "UNVERIFIED", "suggestion": "Check this."},
                    ]
                }
            )
        ]

        verifier = NarrativeVerifier()
        result = await verifier.verify(draft=sample_draft, evidence=sample_evidence)
        updated_draft = verifier.apply_result(sample_draft, result)

        assert updated_draft.verification_status == "HAS_WARNINGS"
        assert len(updated_draft.warnings) >= 1

    async def test_verify_llm_returns_garbage_safe_fallback(self, sample_draft, sample_evidence):
        MockLLMProvider.canned_responses = ["Not valid JSON!!!"]

        verifier = NarrativeVerifier()
        result = await verifier.verify(draft=sample_draft, evidence=sample_evidence)

        assert result.overall_status == "HAS_WARNINGS"
        assert result.unverified_count >= 1

    async def test_injectable_llm_provider(self, sample_draft, sample_evidence):
        class StubLLM:
            async def generate_response(self, prompt, *, system_prompt=None, **kwargs):
                return json.dumps({"findings": [{"claim": "x", "status": "VERIFIED", "source_ref": "S1"}]})

        verifier = NarrativeVerifier(llm_provider=StubLLM())
        result = await verifier.verify(draft=sample_draft, evidence=sample_evidence)
        assert result.overall_status == "VERIFIED"
