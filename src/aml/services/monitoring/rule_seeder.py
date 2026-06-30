from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.models.rule import TenantRule
from aml.services.monitoring.rules import RulePacks
from aml.services.monitoring.schemas import MonitoringRule

PACK_MAPPING: dict[str, str] = {
    "T2-GENERAL": "general",
    "T2-REAL-ESTATE": "real_estate",
    "T2-LEGAL": "legal",
    "T2-ACCOUNTING": "accounting",
}


class RuleSeeder:
    _PACKS: ClassVar[dict[str, str]] = PACK_MAPPING

    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def seed_templates(self) -> int:
        existing_stmt = select(TenantRule.rule_id).where(TenantRule.is_template == True)  # noqa: E712
        result = await self._session.execute(existing_stmt)
        existing_ids = set(result.scalars().all())

        created = 0
        for pack_id, source_key in self._PACKS.items():
            rules = self._load_pack_rules(source_key)
            for rule in rules:
                if rule.id in existing_ids:
                    continue
                tenant_rule = TenantRule(
                    tenant_id=None,
                    rule_id=rule.id,
                    name=rule.name,
                    description=rule.description,
                    conditions=[c.model_dump() for c in rule.conditions],
                    alert_type=rule.alert_type,
                    severity=rule.severity,
                    entity_type=rule.entity_type,
                    is_template=True,
                    pack_id=pack_id,
                )
                self._session.add(tenant_rule)
                existing_ids.add(rule.id)
                created += 1

        if created:
            await self._session.commit()
        return created

    def list_packs(self) -> list[str]:
        return list(self._PACKS.keys())

    @staticmethod
    def _load_pack_rules(source_key: str) -> list[MonitoringRule]:
        if source_key == "general":
            return RulePacks.general()
        return RulePacks.for_entity_type(source_key)
