from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.models.user import User


@dataclass
class TokenPayload:
    user_id: str
    tenant_id: str
    roles: list[str] = field(default_factory=list)
    token_type: str = "access"  # noqa: S105


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105


class AuthProvider(ABC):
    @abstractmethod
    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
        roles: list[str],
        session: AsyncSession,
    ) -> User: ...

    @abstractmethod
    async def authenticate(
        self,
        *,
        email: str,
        password: str,
        tenant_id: str,
        session: AsyncSession,
    ) -> User | None: ...

    @abstractmethod
    def create_access_token(self, user: User) -> str: ...

    @abstractmethod
    def create_refresh_token(self, user: User) -> str: ...

    @abstractmethod
    def verify_token(self, token: str) -> TokenPayload: ...
