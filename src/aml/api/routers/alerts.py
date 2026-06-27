"""
Alerts CRUD API router.

Provides read endpoints for listing and retrieving alerts.
Write operations (create/update) are handled by the agent orchestrator.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.models.alert import Alert, AlertStatus
from aml.db.session import get_db

router = APIRouter(prefix="/alerts", tags=["Alerts"])


# ---------- Response Models ----------


class AlertSummary(BaseModel):
    """Compact alert representation for list views."""

    id: str
    tenant_id: str
    customer_id: str | None
    alert_type: str
    severity: str
    status: str
    title: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AlertDetail(AlertSummary):
    """Full alert representation including the details JSON blob."""

    details: dict[str, Any] | None

    model_config = {"from_attributes": True}


class AlertListResponse(BaseModel):
    """Paginated list of alerts."""

    alerts: list[AlertSummary]
    total: int


# ---------- Helpers ----------


def _require_tenant(x_tenant_id: str | None) -> str:
    """Validate that X-Tenant-ID header is present."""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return x_tenant_id


def _serialize_alert(alert: Alert) -> dict[str, Any]:
    """Convert an Alert ORM instance into a serializable dict."""
    return {
        "id": str(alert.id),
        "tenant_id": alert.tenant_id,
        "customer_id": str(alert.customer_id) if alert.customer_id else None,
        "alert_type": alert.alert_type,
        "severity": alert.severity.value,
        "status": alert.status.value,
        "title": alert.title,
        "description": alert.description,
        "details": alert.details,
        "created_at": alert.created_at,
        "updated_at": alert.updated_at,
    }


# ---------- Endpoints ----------


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    status: str | None = Query(None, description="Filter by alert status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> AlertListResponse:
    """
    List alerts for a tenant.

    Supports optional status filtering and pagination.
    """
    tenant_id = _require_tenant(x_tenant_id)

    # Build query
    stmt = select(Alert).where(Alert.tenant_id == tenant_id)

    if status:
        try:
            status_enum = AlertStatus(status)
        except ValueError as e:
            valid = [s.value for s in AlertStatus]
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{status}'. Valid values: {valid}",
            ) from e
        stmt = stmt.where(Alert.status == status_enum)

    # Count total before pagination
    from sqlalchemy import func

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Apply ordering and pagination
    stmt = stmt.order_by(Alert.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    alerts = result.scalars().all()

    return AlertListResponse(
        alerts=[AlertSummary(**_serialize_alert(a)) for a in alerts],
        total=total,
    )


@router.get("/{alert_id}", response_model=AlertDetail)
async def get_alert(
    alert_id: str,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> AlertDetail:
    """
    Get a single alert by ID.

    Returns full details including the agent investigation results
    stored in the `details` JSON column.
    """
    tenant_id = _require_tenant(x_tenant_id)

    try:
        alert_uuid = uuid.UUID(alert_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid alert ID format (must be UUID): {e!s}") from e

    stmt = select(Alert).where(Alert.id == alert_uuid, Alert.tenant_id == tenant_id)
    result = await db.execute(stmt)
    alert = result.scalar_one_or_none()

    if not alert:
        raise HTTPException(
            status_code=404,
            detail=f"Alert with ID {alert_id} not found under tenant {tenant_id}",
        )

    return AlertDetail(**_serialize_alert(alert))
