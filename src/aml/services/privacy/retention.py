from dataclasses import dataclass
from typing import ClassVar


@dataclass
class RetentionPolicy:
    entity_type: str
    retention_days: int
    grace_period_days: int = 30
    jurisdiction: str = "AU"
    legal_basis: str = ""


_AUSTRAC_BASIS = "AUSTRAC AML/CTF Act s.107"
_NZ_BASIS = "AML/CFT Act 2009"

DEFAULT_POLICIES: list[RetentionPolicy] = [
    RetentionPolicy("transaction", 2555, jurisdiction="AU", legal_basis=_AUSTRAC_BASIS),
    RetentionPolicy("customer", 2555, jurisdiction="AU", legal_basis=_AUSTRAC_BASIS),
    RetentionPolicy("report", 2555, jurisdiction="AU", legal_basis=_AUSTRAC_BASIS),
    RetentionPolicy("alert", 1825, jurisdiction="AU", legal_basis="5 years"),
    RetentionPolicy("case", 1825, jurisdiction="AU", legal_basis="5 years"),
    RetentionPolicy("transaction", 1825, jurisdiction="NZ", legal_basis=_NZ_BASIS),
    RetentionPolicy("customer", 1825, jurisdiction="NZ", legal_basis=_NZ_BASIS),
]


class RetentionPolicyRegistry:
    _DEFAULTS: ClassVar[list[RetentionPolicy]] = DEFAULT_POLICIES

    def __init__(self, *, tenant_overrides: dict[str, int] | None = None) -> None:
        self._overrides = tenant_overrides or {}

    def get_policy(self, entity_type: str, jurisdiction: str = "AU") -> RetentionPolicy | None:
        for policy in self._DEFAULTS:
            if policy.entity_type == entity_type and policy.jurisdiction == jurisdiction:
                override_days = self._overrides.get(entity_type)
                if override_days:
                    return RetentionPolicy(
                        entity_type=entity_type,
                        retention_days=override_days,
                        jurisdiction=jurisdiction,
                        legal_basis=policy.legal_basis,
                    )
                return policy
        return None

    def list_policies(self, jurisdiction: str | None = None) -> list[RetentionPolicy]:
        if jurisdiction:
            return [p for p in self._DEFAULTS if p.jurisdiction == jurisdiction]
        return list(self._DEFAULTS)
