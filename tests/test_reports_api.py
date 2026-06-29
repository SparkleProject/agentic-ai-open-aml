"""Tests for the reporting API router (BE-301 Step 5)."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.db.models.case import Case, CaseStatus
from aml.db.models.report import Report, ReportStatus
from aml.db.models.tenant import Tenant
from aml.services.llm.mock import MockLLMProvider


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


def _setup_db_override(client, db_session):
    from aml.db.session import get_db

    async def override_db():
        yield db_session

    client.app.dependency_overrides[get_db] = override_db


async def _seed_case(db_session, tenant_id):
    case = Case(
        tenant_id=tenant_id,
        status=CaseStatus.INVESTIGATING,
        summary="Structuring investigation",
        reasoning={
            "conclusion": "Structuring confirmed",
            "tools_used": ["SanctionsScreeningTool"],
        },
    )
    db_session.add(case)
    await db_session.commit()
    return case


class TestDraftEndpoint:
    async def test_draft_report(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="test-rpt-1")
        db_session.add(tenant)
        await db_session.flush()
        case = await _seed_case(db_session, tenant_id)

        smr_sections = {
            "Subject Details": "John Smith.",
            "Suspicious Activity Description": "Structuring detected.",
            "Transaction Details": "TXN-001: $9,900.",
            "Reporting Entity Information": "AML Corp.",
            "Reason for Suspicion": "AML/CTF Act s.41.",
        }
        MockLLMProvider.canned_responses = [json.dumps(smr_sections)]

        _setup_db_override(client, db_session)
        response = client.post(
            f"/api/v1/cases/{case.id}/reports/draft",
            json={"report_type": "AUSTRAC_SMR"},
            headers={"X-Tenant-ID": tenant_id},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["report_type"] == "AUSTRAC_SMR"
        assert data["status"] == "draft"
        assert "Subject Details" in data["narrative"]
        assert data["report_id"] is not None

        client.app.dependency_overrides.clear()

    async def test_draft_unknown_report_type(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="test-rpt-2")
        db_session.add(tenant)
        await db_session.flush()
        case = await _seed_case(db_session, tenant_id)

        _setup_db_override(client, db_session)
        response = client.post(
            f"/api/v1/cases/{case.id}/reports/draft",
            json={"report_type": "NONEXISTENT"},
            headers={"X-Tenant-ID": tenant_id},
        )

        assert response.status_code == 400

        client.app.dependency_overrides.clear()


class TestGetEndpoint:
    async def test_get_report(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="test-rpt-3")
        db_session.add(tenant)
        await db_session.flush()

        report = Report(
            tenant_id=tenant_id,
            case_id=uuid.uuid4(),
            report_type="AUSTRAC_SMR",
            status=ReportStatus.DRAFT,
            narrative={"Subject Details": "Content here"},
            evidence_snapshot={},
        )
        db_session.add(report)
        await db_session.commit()

        _setup_db_override(client, db_session)
        response = client.get(
            f"/api/v1/reports/{report.id}",
            headers={"X-Tenant-ID": tenant_id},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["report_type"] == "AUSTRAC_SMR"
        assert data["narrative"]["Subject Details"] == "Content here"

        client.app.dependency_overrides.clear()

    async def test_get_report_not_found(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="test-rpt-4")
        db_session.add(tenant)
        await db_session.flush()

        _setup_db_override(client, db_session)
        response = client.get(
            f"/api/v1/reports/{uuid.uuid4()}",
            headers={"X-Tenant-ID": tenant_id},
        )
        assert response.status_code == 404

        client.app.dependency_overrides.clear()


class TestUpdateEndpoint:
    async def test_update_narrative_sections(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="test-rpt-5")
        db_session.add(tenant)
        await db_session.flush()

        report = Report(
            tenant_id=tenant_id,
            case_id=uuid.uuid4(),
            report_type="AUSTRAC_SMR",
            status=ReportStatus.DRAFT,
            narrative={"Subject Details": "Old content"},
            evidence_snapshot={},
        )
        db_session.add(report)
        await db_session.commit()

        _setup_db_override(client, db_session)
        response = client.put(
            f"/api/v1/reports/{report.id}",
            json={"narrative": {"Subject Details": "Updated by analyst"}},
            headers={"X-Tenant-ID": tenant_id},
        )

        assert response.status_code == 200
        assert response.json()["narrative"]["Subject Details"] == "Updated by analyst"

        client.app.dependency_overrides.clear()


class TestApproveEndpoint:
    async def test_approve_report(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="test-rpt-6")
        db_session.add(tenant)
        await db_session.flush()

        report = Report(
            tenant_id=tenant_id,
            case_id=uuid.uuid4(),
            report_type="AUSTRAC_SMR",
            status=ReportStatus.IN_REVIEW,
            narrative={"Subject Details": "Content"},
            evidence_snapshot={},
        )
        db_session.add(report)
        await db_session.commit()

        _setup_db_override(client, db_session)
        response = client.post(
            f"/api/v1/reports/{report.id}/approve",
            json={"reviewed_by": "analyst@company.com"},
            headers={"X-Tenant-ID": tenant_id},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "approved"
        assert response.json()["reviewed_by"] == "analyst@company.com"

        client.app.dependency_overrides.clear()
