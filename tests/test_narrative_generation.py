"""Tests for narrative generation service (BE-301 Step 2)."""

import json
import uuid

import pytest

from aml.services.llm.mock import MockLLMProvider
from aml.services.reporting.narrative import (
    EvidenceBundle,
    NarrativeDraft,
    NarrativeGenerationService,
)
from aml.services.reporting.templates import TemplateRegistry


@pytest.fixture
def template_registry():
    return TemplateRegistry()


def _make_evidence() -> EvidenceBundle:
    return EvidenceBundle(
        case_id=str(uuid.uuid4()),
        alert_details={
            "alert_type": "structuring_patterns",
            "severity": "high",
            "title": "Multiple sub-threshold deposits",
            "description": "12 deposits of $9,900 within 48 hours.",
        },
        investigation_reasoning={
            "conclusion": "Customer appears to be structuring deposits to avoid reporting thresholds.",
            "tools_used": ["SanctionsScreeningTool", "TransactionLookupTool"],
        },
        customer_profile={
            "name": "John Smith",
            "customer_type": "individual",
            "risk_rating": "high",
        },
        transactions=[
            {"id": "TXN-001", "amount": 9900, "date": "2026-06-01", "direction": "inbound"},
            {"id": "TXN-002", "amount": 9800, "date": "2026-06-01", "direction": "inbound"},
            {"id": "TXN-003", "amount": 9700, "date": "2026-06-02", "direction": "inbound"},
        ],
    )


class TestEvidenceBundle:
    def test_creation(self):
        evidence = _make_evidence()
        assert evidence.case_id is not None
        assert len(evidence.transactions) == 3
        assert evidence.customer_profile["name"] == "John Smith"

    def test_format_as_source_blocks(self):
        evidence = _make_evidence()
        blocks = evidence.format_as_source_blocks()
        assert "[SOURCE-1:" in blocks
        assert "TXN-001" in blocks
        assert "John Smith" in blocks


class TestNarrativeDraft:
    def test_creation(self):
        draft = NarrativeDraft(
            report_type="AUSTRAC_SMR",
            case_id=str(uuid.uuid4()),
            sections={"Subject Details": "John Smith, born 1985..."},
            citations=[],
            verification_status="PENDING",
            warnings=[],
        )
        assert draft.report_type == "AUSTRAC_SMR"
        assert draft.verification_status == "PENDING"

    def test_has_all_required_sections(self):
        registry = TemplateRegistry()
        template = registry.get_template("AUSTRAC_SMR")
        required = template.required_section_names

        draft = NarrativeDraft(
            report_type="AUSTRAC_SMR",
            case_id="case-1",
            sections={name: f"Content for {name}" for name in required},
            citations=[],
            verification_status="PENDING",
            warnings=[],
        )
        missing = draft.missing_sections(required)
        assert missing == []

    def test_missing_sections_detected(self):
        draft = NarrativeDraft(
            report_type="AUSTRAC_SMR",
            case_id="case-1",
            sections={"Subject Details": "content"},
            citations=[],
            verification_status="PENDING",
            warnings=[],
        )
        missing = draft.missing_sections(["Subject Details", "Transaction Details", "Reason for Suspicion"])
        assert "Transaction Details" in missing
        assert "Reason for Suspicion" in missing


class TestNarrativeGenerationService:
    async def test_generate_draft_returns_narrative(self, template_registry):
        smr_sections = {
            "Subject Details": "John Smith, DOB 1985-03-15.",
            "Suspicious Activity Description": "Multiple sub-threshold deposits [SOURCE-1].",
            "Transaction Details": "TXN-001: $9,900 on 2026-06-01 [SOURCE-2].",
            "Reporting Entity Information": "AML Corp, ABN 12345678901.",
            "Reason for Suspicion": "Structuring under AML/CTF Act s.41 [SOURCE-1].",
        }
        MockLLMProvider.canned_responses = [json.dumps(smr_sections)]

        service = NarrativeGenerationService(template_registry=template_registry)
        evidence = _make_evidence()
        draft = await service.generate_draft(
            evidence=evidence,
            report_type="AUSTRAC_SMR",
            tenant_id="tenant-001",
        )

        assert isinstance(draft, NarrativeDraft)
        assert draft.report_type == "AUSTRAC_SMR"
        assert "Subject Details" in draft.sections
        assert draft.verification_status == "PENDING"

    async def test_generate_draft_includes_all_required_sections(self, template_registry):
        template = template_registry.get_template("AUSTRAC_SMR")
        required = template.required_section_names
        smr_sections = {name: f"Content for {name}" for name in required}
        MockLLMProvider.canned_responses = [json.dumps(smr_sections)]

        service = NarrativeGenerationService(template_registry=template_registry)
        evidence = _make_evidence()
        draft = await service.generate_draft(
            evidence=evidence,
            report_type="AUSTRAC_SMR",
            tenant_id="tenant-001",
        )

        missing = draft.missing_sections(required)
        assert missing == []

    async def test_generate_draft_unknown_report_type_raises(self, template_registry):
        service = NarrativeGenerationService(template_registry=template_registry)
        evidence = _make_evidence()
        with pytest.raises(KeyError):
            await service.generate_draft(
                evidence=evidence,
                report_type="NONEXISTENT",
                tenant_id="tenant-001",
            )

    async def test_generate_draft_llm_returns_garbage_fallback(self, template_registry):
        MockLLMProvider.canned_responses = ["This is not valid JSON at all!!!"]

        service = NarrativeGenerationService(template_registry=template_registry)
        evidence = _make_evidence()
        draft = await service.generate_draft(
            evidence=evidence,
            report_type="AUSTRAC_SMR",
            tenant_id="tenant-001",
        )

        assert draft.verification_status == "PENDING"
        assert len(draft.warnings) >= 1
        assert any("parse" in w.lower() for w in draft.warnings)

    async def test_injectable_llm_provider(self, template_registry):
        call_log: list[str] = []

        class SpyLLMProvider:
            async def generate_response(self, prompt, *, system_prompt=None, **kwargs):
                call_log.append(prompt[:50])
                return json.dumps({"Subject Details": "spy content"})

        service = NarrativeGenerationService(
            template_registry=template_registry,
            llm_provider=SpyLLMProvider(),
        )
        evidence = _make_evidence()
        await service.generate_draft(evidence=evidence, report_type="AUSTRAC_SMR", tenant_id="t1")

        assert len(call_log) == 1
