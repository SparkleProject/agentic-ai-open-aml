import uuid
from abc import ABC, abstractmethod

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.models.rule import RuleVersion, TenantRule
from aml.services.monitoring.rule_schemas import CreateRuleRequest, UpdateRuleRequest


class RuleManager(ABC):
    @abstractmethod
    async def create_rule(self, *, tenant_id: str, rule: CreateRuleRequest) -> TenantRule: ...

    @abstractmethod
    async def update_rule(
        self,
        *,
        tenant_id: str,
        rule_id: str,
        update: UpdateRuleRequest,
        changed_by: str | None,
    ) -> TenantRule: ...

    @abstractmethod
    async def delete_rule(self, *, tenant_id: str, rule_id: str) -> None: ...

    @abstractmethod
    async def get_rule(self, *, tenant_id: str, rule_id: str) -> TenantRule | None: ...

    @abstractmethod
    async def list_rules(self, *, tenant_id: str, include_deleted: bool = False) -> list[TenantRule]: ...

    @abstractmethod
    async def adopt_template(self, *, tenant_id: str, template_rule_id: str) -> TenantRule: ...

    @abstractmethod
    async def adopt_pack(self, *, tenant_id: str, pack_id: str) -> list[TenantRule]: ...

    @abstractmethod
    async def list_templates(self) -> list[TenantRule]: ...

    @abstractmethod
    async def get_rule_versions(self, *, tenant_id: str, rule_id: str) -> list[RuleVersion]: ...


class RuleManagementService(RuleManager):
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def create_rule(self, *, tenant_id: str, rule: CreateRuleRequest) -> TenantRule:
        tenant_rule = TenantRule(
            tenant_id=tenant_id,
            rule_id=rule.rule_id,
            name=rule.name,
            description=rule.description,
            conditions=rule.conditions,
            alert_type=rule.alert_type,
            severity=rule.severity,
            enabled=rule.enabled,
            entity_type=rule.entity_type,
        )
        self._session.add(tenant_rule)
        await self._session.commit()
        return tenant_rule

    async def update_rule(
        self,
        *,
        tenant_id: str,
        rule_id: str,
        update: UpdateRuleRequest,
        changed_by: str | None,
    ) -> TenantRule:
        rule = await self._get_active_rule(tenant_id, rule_id)
        if not rule:
            raise ValueError(f"Rule '{rule_id}' not found for tenant '{tenant_id}'")

        snapshot = RuleVersion(
            tenant_rule_id=rule.id,
            version=rule.version,
            conditions=rule.conditions,
            alert_type=rule.alert_type,
            severity=rule.severity,
            enabled=rule.enabled,
            changed_by=changed_by,
            change_reason=update.change_reason,
        )
        self._session.add(snapshot)

        if update.name is not None:
            rule.name = update.name
        if update.description is not None:
            rule.description = update.description
        if update.conditions is not None:
            rule.conditions = update.conditions
        if update.alert_type is not None:
            rule.alert_type = update.alert_type
        if update.severity is not None:
            rule.severity = update.severity
        if update.enabled is not None:
            rule.enabled = update.enabled
        rule.version += 1

        await self._session.commit()
        return rule

    async def delete_rule(self, *, tenant_id: str, rule_id: str) -> None:
        rule = await self._get_active_rule(tenant_id, rule_id)
        if rule:
            rule.is_deleted = True
            await self._session.commit()

    async def get_rule(self, *, tenant_id: str, rule_id: str) -> TenantRule | None:
        return await self._get_active_rule(tenant_id, rule_id)

    async def list_rules(self, *, tenant_id: str, include_deleted: bool = False) -> list[TenantRule]:
        stmt = select(TenantRule).where(
            TenantRule.tenant_id == tenant_id,
            TenantRule.is_template == False,  # noqa: E712
        )
        if not include_deleted:
            stmt = stmt.where(TenantRule.is_deleted == False)  # noqa: E712
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def adopt_template(self, *, tenant_id: str, template_rule_id: str) -> TenantRule:
        stmt = select(TenantRule).where(
            TenantRule.id == uuid.UUID(template_rule_id),
            TenantRule.is_template == True,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        template = result.scalar_one_or_none()
        if not template:
            raise ValueError(f"Template '{template_rule_id}' not found")

        adopted = TenantRule(
            tenant_id=tenant_id,
            rule_id=template.rule_id,
            name=template.name,
            description=template.description,
            conditions=template.conditions,
            alert_type=template.alert_type,
            severity=template.severity,
            entity_type=template.entity_type,
            pack_id=template.pack_id,
        )
        self._session.add(adopted)
        await self._session.commit()
        return adopted

    async def adopt_pack(self, *, tenant_id: str, pack_id: str) -> list[TenantRule]:
        stmt = select(TenantRule).where(
            TenantRule.is_template == True,  # noqa: E712
            TenantRule.pack_id == pack_id,
        )
        result = await self._session.execute(stmt)
        templates = result.scalars().all()

        adopted: list[TenantRule] = []
        for template in templates:
            rule = TenantRule(
                tenant_id=tenant_id,
                rule_id=template.rule_id,
                name=template.name,
                description=template.description,
                conditions=template.conditions,
                alert_type=template.alert_type,
                severity=template.severity,
                entity_type=template.entity_type,
                pack_id=template.pack_id,
            )
            self._session.add(rule)
            adopted.append(rule)

        if adopted:
            await self._session.commit()
        return adopted

    async def list_templates(self) -> list[TenantRule]:
        stmt = select(TenantRule).where(TenantRule.is_template == True)  # noqa: E712
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_rule_versions(self, *, tenant_id: str, rule_id: str) -> list[RuleVersion]:
        rule = await self._get_active_rule(tenant_id, rule_id, include_deleted=True)
        if not rule:
            return []
        stmt = select(RuleVersion).where(RuleVersion.tenant_rule_id == rule.id).order_by(RuleVersion.version)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _get_active_rule(
        self,
        tenant_id: str,
        rule_id: str,
        *,
        include_deleted: bool = False,
    ) -> TenantRule | None:
        stmt = select(TenantRule).where(
            TenantRule.tenant_id == tenant_id,
            TenantRule.rule_id == rule_id,
            TenantRule.is_template == False,  # noqa: E712
        )
        if not include_deleted:
            stmt = stmt.where(TenantRule.is_deleted == False)  # noqa: E712
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
