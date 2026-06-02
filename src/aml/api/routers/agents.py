"""
Agents API router.

Provides endpoints for initiating and monitoring alert investigations
driven by the Agentic Core.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml.agents.orchestrator import build_orchestrator
from aml.db.models.alert import Alert, AlertStatus
from aml.db.session import get_db

router = APIRouter(prefix="/agents", tags=["Agents"])


def _require_tenant(x_tenant_id: str | None) -> str:
    """Validate that X-Tenant-ID header is present."""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return x_tenant_id


@router.post("/alerts/{alert_id}/investigate")
async def investigate_alert(
    alert_id: str,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Trigger the Agentic Orchestrator on an Alert.

    1. Fetches the Alert from the DB.
    2. Runs the compiled LangGraph workflow.
    3. Updates DB state (Alert status, observations, final conclusion).
    """
    tenant_id = _require_tenant(x_tenant_id)

    # Validate alert_id as UUID
    try:
        alert_uuid = uuid.UUID(alert_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid alert ID format (must be UUID): {e!s}") from e

    # 1. Fetch Alert
    stmt = select(Alert).where(Alert.id == alert_uuid, Alert.tenant_id == tenant_id)
    result = await db.execute(stmt)
    alert = result.scalar_one_or_none()

    if not alert:
        raise HTTPException(
            status_code=404,
            detail=f"Alert with ID {alert_id} not found under tenant {tenant_id}",
        )

    # Set status to INVESTIGATING
    alert.status = AlertStatus.INVESTIGATING
    await db.commit()

    # Map alert type to initial specialized active agent
    initial_agent = "SanctionsAgent"
    alert_type_lower = alert.alert_type.lower()
    if "sanction" in alert_type_lower or "pep" in alert_type_lower:
        initial_agent = "SanctionsAgent"
    elif "structuring" in alert_type_lower or "transaction" in alert_type_lower or "deposit" in alert_type_lower:
        initial_agent = "TransactionMonitorAgent"
    elif "cdd" in alert_type_lower or "kyc" in alert_type_lower or "ubo" in alert_type_lower:
        initial_agent = "CDDAgent"

    # 2. Run LangGraph Orchestrator
    orchestrator = build_orchestrator()
    initial_state = {
        "alert_id": str(alert.id),
        "tenant_id": tenant_id,
        "severity": alert.severity.value,
        "plan": "",
        "executed_tools": [],
        "observations": [],
        "conclusion": {},
        "active_agent": initial_agent,
        "agent_history": [],
    }

    try:
        final_state = await orchestrator.ainvoke(initial_state)
    except Exception as e:
        alert.status = AlertStatus.NEW  # Reset status on crash
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Agent runtime crash: {e!s}") from e

    # 3. Update database with findings
    conclusion = final_state.get("conclusion", {})
    observations = final_state.get("observations", [])

    # Simply resolve the alert for now
    alert.status = AlertStatus.RESOLVED

    # Store conclusion & observations in Alert.details
    if alert.details is None:
        alert.details = {}
    alert.details["agent_conclusion"] = conclusion
    alert.details["observations"] = observations

    await db.commit()

    return {
        "status": "success",
        "alert_id": alert_id,
        "tenant_id": tenant_id,
        "final_alert_status": alert.status.value,
        "conclusion": conclusion,
        "observations": observations,
    }
