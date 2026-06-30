"""Governance logging API router (BE-402)."""

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.models.governance_log import GovernanceLog
from aml.db.session import get_db
from aml.services.governance.verifier import ChainVerifier

router = APIRouter(prefix="/governance", tags=["Governance"])


def _require_tenant(x_tenant_id: str | None) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return x_tenant_id


@router.get("/logs")
async def list_logs(
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    event_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)

    stmt = select(GovernanceLog).where(GovernanceLog.tenant_id == tenant_id)
    if event_type:
        stmt = stmt.where(GovernanceLog.event_type == event_type)
    stmt = stmt.order_by(GovernanceLog.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(stmt)
    logs = result.scalars().all()

    return {
        "logs": [_serialize_log(log) for log in logs],
        "count": len(logs),
    }


@router.get("/logs/{log_id}")
async def get_log(
    log_id: str,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)

    import uuid

    try:
        log_uuid = uuid.UUID(log_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid log ID: {e}") from e

    stmt = select(GovernanceLog).where(GovernanceLog.id == log_uuid, GovernanceLog.tenant_id == tenant_id)
    result = await db.execute(stmt)
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")

    return _serialize_log(log)


@router.post("/verify")
async def verify_chain(
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    verifier = ChainVerifier(session=db)
    result = await verifier.verify_chain(tenant_id)

    return {
        "is_valid": result.is_valid,
        "total_entries": result.total_entries,
        "first_break_at": result.first_break_at,
        "error": result.error,
    }


def _serialize_log(log: GovernanceLog) -> dict[str, Any]:
    return {
        "id": str(log.id),
        "tenant_id": log.tenant_id,
        "timestamp": str(log.created_at),
        "event_type": log.event_type,
        "agent_id": log.agent_id,
        "model_id": log.model_id,
        "case_id": str(log.case_id) if log.case_id else None,
        "input_tokens": log.input_tokens,
        "output_tokens": log.output_tokens,
        "latency_ms": log.latency_ms,
        "status": log.status,
        "content_hash": log.content_hash,
        "details": {
            "input_summary": log.input_summary,
            "output_summary": log.output_summary,
            "reasoning_chain": log.reasoning_chain,
        },
    }
