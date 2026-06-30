"""Tests for KYC/CDD pipeline and API (BE-302)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.db.models.cdd_record import CDDRecord, CDDStatus, CDDType
from aml.db.models.customer import Customer, CustomerType
from aml.db.models.tenant import Tenant
from aml.services.kyc.adapters.mock import MockIdentityVerifier
from aml.services.kyc.pipeline import CDDPipeline
from aml.services.kyc.protocol import IdentityVerificationProvider, VerificationResult


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


class TestMockIdentityVerifier:
    async def test_returns_verified(self):
        verifier = MockIdentityVerifier()
        result = await verifier.verify_identity(name="John Smith", customer_type="individual")

        assert result.verified is True
        assert result.confidence > 0.5
        assert len(result.checks) >= 1


class TestCDDPipeline:
    async def test_full_onboarding_low_risk(self):
        pipeline = CDDPipeline()
        record = await pipeline.run_onboarding(
            customer_name="John Smith",
            customer_type="individual",
            customer_id=str(uuid.uuid4()),
            tenant_id="tenant-001",
        )

        assert isinstance(record, CDDRecord)
        assert record.status == CDDStatus.COMPLETE
        assert record.onboarding_stage == "COMPLETE"
        assert record.decision == "APPROVED"
        assert record.overall_risk_score < 30
        assert record.id_verification is not None
        assert record.pep_result is not None
        assert record.sanctions_result is not None
        assert record.adverse_media_result is not None
        assert record.risk_assessment is not None

    async def test_high_risk_entity_escalates(self):
        pipeline = CDDPipeline()
        record = await pipeline.run_onboarding(
            customer_name="putin",
            customer_type="trust",
            customer_id=str(uuid.uuid4()),
            tenant_id="tenant-001",
            jurisdiction="IR",
        )

        assert record.status == CDDStatus.ESCALATED
        assert record.overall_risk_score > 30

    async def test_stages_progress_sequentially(self):
        pipeline = CDDPipeline()
        record = await pipeline.run_onboarding(
            customer_name="Jane Doe",
            customer_type="individual",
            customer_id=str(uuid.uuid4()),
            tenant_id="tenant-001",
        )

        assert record.onboarding_stage == "COMPLETE"
        assert record.id_verification is not None
        assert record.pep_result is not None
        assert record.sanctions_result is not None

    async def test_injectable_id_verifier(self):
        class FailingVerifier(IdentityVerificationProvider):
            async def verify_identity(self, *, name, customer_type, metadata=None):
                return VerificationResult(verified=False, confidence=0.1, provider_ref="FAIL")

        pipeline = CDDPipeline(id_verifier=FailingVerifier())
        record = await pipeline.run_onboarding(
            customer_name="Test",
            customer_type="individual",
            customer_id=str(uuid.uuid4()),
            tenant_id="tenant-001",
        )

        assert record.id_verification is not None
        assert record.id_verification["verified"] is False

    async def test_cdd_type_is_set(self):
        pipeline = CDDPipeline()
        record = await pipeline.run_onboarding(
            customer_name="Test",
            customer_type="individual",
            customer_id=str(uuid.uuid4()),
            tenant_id="tenant-001",
            cdd_type=CDDType.ENHANCED,
        )

        assert record.cdd_type == CDDType.ENHANCED


class TestKYCAPI:
    async def test_onboard_customer(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        customer_id = str(uuid.uuid4())

        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="kyc-api-1")
        db_session.add(tenant)
        await db_session.flush()

        customer = Customer(
            id=uuid.UUID(customer_id),
            tenant_id=tenant_id,
            external_id="EXT-001",
            name="John Smith",
            customer_type=CustomerType.INDIVIDUAL,
        )
        db_session.add(customer)
        await db_session.commit()

        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        resp = client.post(
            "/api/v1/kyc/onboard",
            json={"customer_id": customer_id},
            headers={"X-Tenant-ID": tenant_id},
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] in ("complete", "escalated")
        assert data["onboarding_stage"] == "COMPLETE"
        assert data["decision"] in ("APPROVED", "MANUAL_REVIEW", "REJECTED")

        client.app.dependency_overrides.clear()

    async def test_onboard_customer_not_found(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="kyc-api-2")
        db_session.add(tenant)
        await db_session.flush()

        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        resp = client.post(
            "/api/v1/kyc/onboard",
            json={"customer_id": str(uuid.uuid4())},
            headers={"X-Tenant-ID": tenant_id},
        )

        assert resp.status_code == 404

        client.app.dependency_overrides.clear()

    async def test_get_customer_cdd(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        customer_id = str(uuid.uuid4())

        tenant = Tenant(id=uuid.UUID(tenant_id), name="Test", slug="kyc-api-3")
        db_session.add(tenant)
        await db_session.flush()

        record = CDDRecord(
            tenant_id=tenant_id,
            customer_id=uuid.UUID(customer_id),
            cdd_type=CDDType.INITIAL,
            status=CDDStatus.COMPLETE,
            onboarding_stage="COMPLETE",
            overall_risk_score=15,
            decision="APPROVED",
        )
        db_session.add(record)
        await db_session.commit()

        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        resp = client.get(
            f"/api/v1/kyc/customers/{customer_id}",
            headers={"X-Tenant-ID": tenant_id},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["records"]) == 1
        assert data["latest"]["decision"] == "APPROVED"

        client.app.dependency_overrides.clear()
