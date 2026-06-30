from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CRMCustomer:
    external_id: str
    name: str
    email: str | None = None
    entity_type: str = "individual"
    jurisdiction: str = "AU"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str | None = None
    expires_at: str | None = None
    scope: str = ""


class CRMIntegration(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    async def pull_customers(self, tenant_id: str) -> list[CRMCustomer]: ...

    @abstractmethod
    async def push_risk_score(
        self,
        tenant_id: str,
        external_id: str,
        score: int,
        flags: list[str],
    ) -> bool: ...
