"""Reporting API router (BE-301)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.models.case import Case
from aml.db.models.report import Report, ReportStatus
from aml.db.session import get_db
from aml.services.reporting.narrative import (
    EvidenceBundle,
    NarrativeGenerationService,
)
from aml.services.reporting.templates import TemplateRegistry

router = APIRouter(tags=["Reports"])


def _require_tenant(x_tenant_id: str | None) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return x_tenant_id


class DraftRequest(BaseModel):
    report_type: str


class UpdateRequest(BaseModel):
    narrative: dict[str, str]


class ApproveRequest(BaseModel):
    reviewed_by: str


@router.post("/cases/{case_id}/reports/draft", status_code=201)
async def draft_report(
    case_id: str,
    body: DraftRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)

    try:
        case_uuid = uuid.UUID(case_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid case ID: {e!s}") from e

    stmt = select(Case).where(Case.id == case_uuid, Case.tenant_id == tenant_id)
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    registry = TemplateRegistry()
    try:
        registry.get_template(body.report_type)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Unknown report type: {body.report_type}") from e

    evidence = EvidenceBundle(
        case_id=str(case.id),
        alert_details={},
        investigation_reasoning=case.reasoning or {},
        customer_profile={},
        transactions=[],
    )

    service = NarrativeGenerationService(template_registry=registry)
    draft = await service.generate_draft(
        evidence=evidence,
        report_type=body.report_type,
        tenant_id=tenant_id,
    )

    report = Report(
        tenant_id=tenant_id,
        case_id=case.id,
        report_type=body.report_type,
        status=ReportStatus.DRAFT,
        narrative=draft.sections,
        evidence_snapshot=evidence.model_dump(),
        verification_result=None,
    )
    db.add(report)
    await db.commit()

    return {
        "report_id": str(report.id),
        "report_type": report.report_type,
        "status": report.status.value,
        "narrative": report.narrative,
        "warnings": draft.warnings,
    }


@router.get("/reports/{report_id}")
async def get_report(
    report_id: str,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    report = await _fetch_report(db, report_id, tenant_id)

    return {
        "report_id": str(report.id),
        "report_type": report.report_type,
        "status": report.status.value,
        "narrative": report.narrative,
        "evidence_snapshot": report.evidence_snapshot,
        "verification_result": report.verification_result,
        "reviewed_by": report.reviewed_by,
        "submitted_at": str(report.submitted_at) if report.submitted_at else None,
    }


@router.put("/reports/{report_id}")
async def update_report(
    report_id: str,
    body: UpdateRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    report = await _fetch_report(db, report_id, tenant_id)

    report.narrative = body.narrative
    await db.commit()

    return {
        "report_id": str(report.id),
        "status": report.status.value,
        "narrative": report.narrative,
    }


@router.post("/reports/{report_id}/approve")
async def approve_report(
    report_id: str,
    body: ApproveRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    report = await _fetch_report(db, report_id, tenant_id)

    report.status = ReportStatus.APPROVED
    report.reviewed_by = body.reviewed_by
    await db.commit()

    return {
        "report_id": str(report.id),
        "status": report.status.value,
        "reviewed_by": report.reviewed_by,
    }


async def _fetch_report(db: AsyncSession, report_id: str, tenant_id: str) -> Report:
    try:
        report_uuid = uuid.UUID(report_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid report ID: {e!s}") from e

    stmt = select(Report).where(Report.id == report_uuid, Report.tenant_id == tenant_id)
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    return report
