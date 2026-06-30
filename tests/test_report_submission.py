"""Tests for regulatory report submission (BE-303)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.db.models.report import Report, ReportStatus
from aml.db.models.tenant import Tenant
from aml.services.reporting.submission.austrac import AUSTRACAdapter
from aml.services.reporting.submission.nz_fiu import NZFIUAdapter
from aml.services.reporting.submission.protocol import SubmissionResult
from aml.services.reporting.submission.service import ReportSubmissionService


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


class TestAUSTRACAdapter:
    async def test_format_payload_returns_xml(self):
        adapter = AUSTRACAdapter(mock_mode=True)
        payload = await adapter.format_payload(
            "AUSTRAC_SMR",
            {"Subject Details": "John Smith", "Reason for Suspicion": "Structuring"},
        )
        assert b"<suspicious_matter_report>" in payload
        assert b"John Smith" in payload

    async def test_submit_mock_returns_success(self):
        adapter = AUSTRACAdapter(mock_mode=True)
        payload = b"<test/>"
        result = await adapter.submit(payload)
        assert result.success is True
        assert result.reference is not None
        assert result.reference.startswith("AUSTRAC-MOCK-")

    async def test_check_status_mock(self):
        adapter = AUSTRACAdapter(mock_mode=True)
        status = await adapter.check_status("AUSTRAC-MOCK-12345678")
        assert status.status == "ACCEPTED"


class TestNZFIUAdapter:
    async def test_format_payload_returns_xml(self):
        adapter = NZFIUAdapter(mock_mode=True)
        payload = await adapter.format_payload(
            "NZ_SAR",
            {"Subject Details": "Jane Doe", "Reason for Suspicion": "Layering"},
        )
        assert b"<goAML_SAR>" in payload
        assert b"Jane Doe" in payload

    async def test_submit_mock_returns_success(self):
        adapter = NZFIUAdapter(mock_mode=True)
        result = await adapter.submit(b"<test/>")
        assert result.success is True
        assert result.reference is not None


class TestReportSubmissionService:
    def _make_report(self, **overrides) -> Report:
        defaults = {
            "tenant_id": "tenant-001",
            "case_id": uuid.uuid4(),
            "report_type": "AUSTRAC_SMR",
            "status": ReportStatus.APPROVED,
            "narrative": {"Subject Details": "Test", "Reason for Suspicion": "Testing"},
            "evidence_snapshot": {},
        }
        defaults.update(overrides)
        return Report(**defaults)

    async def test_submit_approved_report(self):
        report = self._make_report()
        service = ReportSubmissionService()
        result = await service.submit_report(report)

        assert result.success is True
        assert result.reference is not None
        assert report.status == ReportStatus.SUBMITTED
        assert report.submitted_at is not None

    async def test_submit_non_approved_fails(self):
        report = self._make_report(status=ReportStatus.DRAFT)
        service = ReportSubmissionService()
        result = await service.submit_report(report)

        assert result.success is False
        assert "APPROVED" in (result.error or "")

    async def test_submit_unknown_type_fails(self):
        report = self._make_report(report_type="UNKNOWN_TYPE")
        service = ReportSubmissionService()
        result = await service.submit_report(report)

        assert result.success is False
        assert "adapter" in (result.error or "").lower()

    async def test_submit_nz_sar(self):
        report = self._make_report(report_type="NZ_SAR")
        service = ReportSubmissionService()
        result = await service.submit_report(report)

        assert result.success is True
        assert result.reference is not None
        assert "NZFIU" in result.reference

    async def test_check_status(self):
        report = self._make_report()
        report.submission_reference = "AUSTRAC-MOCK-12345678"
        report.status = ReportStatus.SUBMITTED

        service = ReportSubmissionService()
        status = await service.check_status(report)

        assert status.status == "ACCEPTED"

    async def test_check_status_no_reference(self):
        report = self._make_report()
        service = ReportSubmissionService()
        status = await service.check_status(report)

        assert status.status == "UNKNOWN"

    async def test_injectable_adapter(self):
        class FailAdapter(AUSTRACAdapter):
            async def submit(self, payload):
                return SubmissionResult(success=False, error="Intentional failure")

        report = self._make_report()
        service = ReportSubmissionService(adapter_overrides={"AUSTRAC_SMR": FailAdapter()})
        result = await service.submit_report(report)

        assert result.success is False


class TestSubmissionAPI:
    async def test_submit_endpoint(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="submit-1")
        db_session.add(tenant)
        await db_session.flush()

        report = Report(
            tenant_id=tenant_id,
            case_id=uuid.uuid4(),
            report_type="AUSTRAC_SMR",
            status=ReportStatus.APPROVED,
            narrative={"Subject Details": "Test"},
            evidence_snapshot={},
        )
        db_session.add(report)
        await db_session.commit()

        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        resp = client.post(
            f"/api/v1/reports/{report.id}/submit",
            headers={"X-Tenant-ID": tenant_id},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["reference"] is not None
        assert data["status"] == "submitted"

        client.app.dependency_overrides.clear()

    async def test_submission_status_endpoint(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="submit-2")
        db_session.add(tenant)
        await db_session.flush()

        report = Report(
            tenant_id=tenant_id,
            case_id=uuid.uuid4(),
            report_type="AUSTRAC_SMR",
            status=ReportStatus.SUBMITTED,
            narrative={},
            evidence_snapshot={},
            submission_reference="AUSTRAC-MOCK-TEST",
        )
        db_session.add(report)
        await db_session.commit()

        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        resp = client.get(
            f"/api/v1/reports/{report.id}/submission-status",
            headers={"X-Tenant-ID": tenant_id},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ACCEPTED"

        client.app.dependency_overrides.clear()
