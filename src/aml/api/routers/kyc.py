"""KYC/CDD API router (BE-302)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.models.cdd_record import CDDRecord
from aml.db.models.customer import Customer
from aml.db.session import get_db
from aml.services.kyc.pipeline import CDDPipeline

router = APIRouter(prefix="/kyc", tags=["KYC"])


def _require_tenant(x_tenant_id: str | None) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return x_tenant_id


class OnboardRequest(BaseModel):
    customer_id: str
    documents: list[dict[str, Any]] | None = None


@router.post("/onboard", status_code=201)
async def onboard_customer(
    body: OnboardRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)

    try:
        customer_uuid = uuid.UUID(body.customer_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid customer_id: {e}") from e

    stmt = select(Customer).where(Customer.id == customer_uuid, Customer.tenant_id == tenant_id)
    result = await db.execute(stmt)
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    pipeline = CDDPipeline()
    record = await pipeline.run_onboarding(
        customer_name=customer.name,
        customer_type=customer.customer_type.value,
        customer_id=str(customer.id),
        tenant_id=tenant_id,
    )

    db.add(record)
    await db.commit()

    return _serialize_cdd(record)


@router.get("/customers")
async def list_kyc_customers(
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)

    stmt = select(Customer).where(Customer.tenant_id == tenant_id)
    result = await db.execute(stmt)
    customers = result.scalars().all()

    customer_list = []
    for c in customers:
        cdd_stmt = (
            select(CDDRecord)
            .where(CDDRecord.customer_id == c.id, CDDRecord.tenant_id == tenant_id)
            .order_by(CDDRecord.created_at.desc())
            .limit(1)
        )
        cdd_result = await db.execute(cdd_stmt)
        latest_cdd = cdd_result.scalar_one_or_none()

        customer_list.append(
            {
                "id": str(c.id),
                "name": c.name,
                "entityType": c.customer_type.value,
                "jurisdiction": (c.metadata_ or {}).get("jurisdiction", "AU"),
                "tranche": (c.metadata_ or {}).get("tranche", "Tranche 2"),
                "overallRiskLevel": _get_risk_level(latest_cdd),
                "onboardingStage": latest_cdd.onboarding_stage if latest_cdd else "PENDING",
                "onboardingProgress": _compute_progress(latest_cdd),
                "overallRiskScore": latest_cdd.overall_risk_score if latest_cdd else 0,
                "status": latest_cdd.status.value if latest_cdd else "pending",
                "decision": latest_cdd.decision if latest_cdd else None,
            }
        )

    return {"customers": customer_list, "count": len(customer_list)}


def _get_risk_level(cdd: CDDRecord | None) -> str:
    if not cdd or not cdd.risk_assessment:
        return "LOW"
    return cdd.risk_assessment.get("risk_level", "LOW").upper()


def _compute_progress(cdd: CDDRecord | None) -> int:
    if not cdd:
        return 0
    stage_map = {
        "PENDING": 0,
        "ID_VERIFICATION": 20,
        "PEP_SCREENING": 40,
        "SANCTIONS_CHECK": 60,
        "ADVERSE_MEDIA": 70,
        "RISK_SCORING": 90,
        "COMPLETE": 100,
    }
    return stage_map.get(cdd.onboarding_stage, 0)


@router.get("/customers/{customer_id}")
async def get_customer_cdd(
    customer_id: str,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)

    try:
        customer_uuid = uuid.UUID(customer_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid customer_id: {e}") from e

    stmt = (
        select(CDDRecord)
        .where(CDDRecord.customer_id == customer_uuid, CDDRecord.tenant_id == tenant_id)
        .order_by(CDDRecord.created_at.desc())
    )
    result = await db.execute(stmt)
    records = result.scalars().all()

    return {
        "customer_id": customer_id,
        "records": [_serialize_cdd(r) for r in records],
        "latest": _serialize_cdd(records[0]) if records else None,
    }


def _serialize_cdd(record: CDDRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "customer_id": str(record.customer_id),
        "cdd_type": record.cdd_type.value,
        "status": record.status.value,
        "onboarding_stage": record.onboarding_stage,
        "overall_risk_score": record.overall_risk_score,
        "decision": record.decision,
        "risk_assessment": record.risk_assessment,
        "id_verification": record.id_verification,
        "pep_result": record.pep_result,
        "sanctions_result": record.sanctions_result,
        "adverse_media_result": record.adverse_media_result,
    }
