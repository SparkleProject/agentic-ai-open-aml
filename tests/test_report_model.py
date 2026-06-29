"""Tests for the Report ORM model (BE-301 Step 4)."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.db.models.report import Report, ReportStatus
from aml.db.models.tenant import Tenant


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


class TestReportStatus:
    def test_all_status_values(self):
        assert ReportStatus.DRAFT == "draft"
        assert ReportStatus.IN_REVIEW == "in_review"
        assert ReportStatus.APPROVED == "approved"
        assert ReportStatus.SUBMITTED == "submitted"
        assert ReportStatus.REJECTED == "rejected"


class TestReportModel:
    async def test_create_report(self, db_session: AsyncSession):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="test-report-1")
        db_session.add(tenant)
        await db_session.flush()

        case_id = uuid.uuid4()
        report = Report(
            tenant_id=tenant_id,
            case_id=case_id,
            report_type="AUSTRAC_SMR",
            status=ReportStatus.DRAFT,
            narrative={"Subject Details": "John Smith"},
            evidence_snapshot={"alert": {"type": "structuring"}},
        )
        db_session.add(report)
        await db_session.commit()

        assert report.id is not None
        assert report.status == ReportStatus.DRAFT
        assert report.narrative["Subject Details"] == "John Smith"
        assert report.submitted_at is None

    async def test_report_status_transitions(self, db_session: AsyncSession):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="test-report-2")
        db_session.add(tenant)
        await db_session.flush()

        report = Report(
            tenant_id=tenant_id,
            case_id=uuid.uuid4(),
            report_type="NZ_SAR",
            status=ReportStatus.DRAFT,
            narrative={},
            evidence_snapshot={},
        )
        db_session.add(report)
        await db_session.commit()

        report.status = ReportStatus.IN_REVIEW
        await db_session.commit()
        assert report.status == ReportStatus.IN_REVIEW

        report.status = ReportStatus.APPROVED
        report.reviewed_by = "analyst@company.com"
        await db_session.commit()
        assert report.reviewed_by == "analyst@company.com"

    async def test_report_verification_result_storage(self, db_session: AsyncSession):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="test-report-3")
        db_session.add(tenant)
        await db_session.flush()

        report = Report(
            tenant_id=tenant_id,
            case_id=uuid.uuid4(),
            report_type="AUSTRAC_SMR",
            status=ReportStatus.DRAFT,
            narrative={"Subject Details": "Jane Doe"},
            evidence_snapshot={},
            verification_result={
                "overall_status": "HAS_WARNINGS",
                "findings": [{"claim": "x", "status": "UNVERIFIED"}],
            },
        )
        db_session.add(report)
        await db_session.commit()

        await db_session.refresh(report)
        assert report.verification_result["overall_status"] == "HAS_WARNINGS"
