import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from aml.db.models.rule import TenantRule
from aml.services.monitoring.schemas import MonitoringRule, RuleCondition


@dataclass
class _CacheEntry:
    rules: list[MonitoringRule]
    loaded_at: float


class RuleCache:
    def __init__(
        self,
        *,
        ttl_seconds: float = 60.0,
        loader: Callable[..., Coroutine[Any, Any, list[TenantRule]]] | None = None,
    ) -> None:
        self._ttl = ttl_seconds
        self._loader = loader
        self._cache: dict[str, _CacheEntry] = {}

    async def get_rules(
        self,
        *,
        tenant_id: str,
        entity_type: str | None = None,
    ) -> list[MonitoringRule]:
        cache_key = tenant_id
        entry = self._cache.get(cache_key)

        if entry is None or self._is_expired(entry):
            raw_rules = await self._load(tenant_id)
            converted = [self._convert(r) for r in raw_rules if r.enabled and not r.is_deleted]
            self._cache[cache_key] = _CacheEntry(rules=converted, loaded_at=time.monotonic())
            entry = self._cache[cache_key]

        if entity_type is not None:
            return [r for r in entry.rules if r.entity_type is None or r.entity_type == entity_type]
        return list(entry.rules)

    def invalidate(self, tenant_id: str) -> None:
        keys_to_remove = [k for k in self._cache if k == tenant_id]
        for k in keys_to_remove:
            del self._cache[k]

    def invalidate_all(self) -> None:
        self._cache.clear()

    def _is_expired(self, entry: _CacheEntry) -> bool:
        return (time.monotonic() - entry.loaded_at) >= self._ttl

    async def _load(self, tenant_id: str) -> list[TenantRule]:
        if self._loader is not None:
            return await self._loader(tenant_id)
        return []

    @staticmethod
    def _convert(rule: TenantRule) -> MonitoringRule:
        conditions = [RuleCondition(**c) for c in rule.conditions] if rule.conditions else []
        return MonitoringRule(
            id=rule.rule_id,
            name=rule.name,
            description=rule.description or "",
            conditions=conditions,
            alert_type=rule.alert_type,
            severity=rule.severity,
            enabled=rule.enabled,
            entity_type=rule.entity_type,
        )
