"""Rule management API router (BE-305)."""

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.session import get_db
from aml.services.monitoring.rule_management import RuleManagementService
from aml.services.monitoring.rule_schemas import CreateRuleRequest, UpdateRuleRequest
from aml.services.monitoring.rule_seeder import RuleSeeder

router = APIRouter(tags=["Rules"])


def _require_tenant(x_tenant_id: str | None) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return x_tenant_id


def _serialize_rule(rule: Any) -> dict[str, Any]:
    return {
        "id": str(rule.id),
        "rule_id": rule.rule_id,
        "name": rule.name,
        "description": rule.description,
        "conditions": rule.conditions,
        "alert_type": rule.alert_type,
        "severity": rule.severity.value,
        "enabled": rule.enabled,
        "entity_type": rule.entity_type,
        "version": rule.version,
        "is_template": rule.is_template,
        "pack_id": rule.pack_id,
    }


@router.post("/rules", status_code=201)
async def create_rule(
    body: CreateRuleRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    svc = RuleManagementService(session=db)
    rule = await svc.create_rule(tenant_id=tenant_id, rule=body)
    return _serialize_rule(rule)


@router.get("/rules")
async def list_rules(
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    svc = RuleManagementService(session=db)
    rules = await svc.list_rules(tenant_id=tenant_id)
    return {"rules": [_serialize_rule(r) for r in rules]}


@router.get("/rules/templates")
async def list_templates(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = RuleManagementService(session=db)
    templates = await svc.list_templates()
    return {"templates": [_serialize_rule(t) for t in templates]}


@router.get("/rules/templates/packs")
async def list_packs() -> dict[str, Any]:
    seeder = RuleSeeder.__new__(RuleSeeder)
    return {"packs": seeder.list_packs()}


@router.get("/rules/{rule_id}")
async def get_rule(
    rule_id: str,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    svc = RuleManagementService(session=db)
    rule = await svc.get_rule(tenant_id=tenant_id, rule_id=rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    return _serialize_rule(rule)


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: str,
    body: UpdateRuleRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    svc = RuleManagementService(session=db)
    try:
        rule = await svc.update_rule(
            tenant_id=tenant_id,
            rule_id=rule_id,
            update=body,
            changed_by=None,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _serialize_rule(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> None:
    tenant_id = _require_tenant(x_tenant_id)
    svc = RuleManagementService(session=db)
    await svc.delete_rule(tenant_id=tenant_id, rule_id=rule_id)


@router.get("/rules/{rule_id}/versions")
async def get_rule_versions(
    rule_id: str,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    svc = RuleManagementService(session=db)
    versions = await svc.get_rule_versions(tenant_id=tenant_id, rule_id=rule_id)
    return {
        "versions": [
            {
                "version": v.version,
                "conditions": v.conditions,
                "alert_type": v.alert_type,
                "severity": v.severity.value,
                "enabled": v.enabled,
                "changed_by": v.changed_by,
                "change_reason": v.change_reason,
            }
            for v in versions
        ]
    }


@router.post("/rules/adopt-template/{template_id}", status_code=201)
async def adopt_template(
    template_id: str,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    svc = RuleManagementService(session=db)
    try:
        rule = await svc.adopt_template(tenant_id=tenant_id, template_rule_id=template_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _serialize_rule(rule)


@router.post("/rules/adopt-pack/{pack_id}", status_code=201)
async def adopt_pack(
    pack_id: str,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    svc = RuleManagementService(session=db)
    rules = await svc.adopt_pack(tenant_id=tenant_id, pack_id=pack_id)
    return {"adopted": [_serialize_rule(r) for r in rules], "count": len(rules)}
