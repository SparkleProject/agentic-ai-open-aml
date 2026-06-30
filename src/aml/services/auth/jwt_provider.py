from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.models.user import User
from aml.services.auth.provider import AuthProvider, TokenPayload


class JWTAuthProvider(AuthProvider):
    def __init__(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 30,
        refresh_token_expire_days: int = 7,
    ) -> None:
        self._secret = secret_key
        self._algorithm = algorithm
        self._access_expire = access_token_expire_minutes
        self._refresh_expire = refresh_token_expire_days

    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str,
        roles: list[str],
        session: AsyncSession,
    ) -> User:
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user = User(
            tenant_id=tenant_id,
            email=email,
            password_hash=password_hash,
            full_name=full_name,
            roles=roles,
        )
        session.add(user)
        await session.commit()
        return user

    async def authenticate(
        self,
        *,
        email: str,
        password: str,
        tenant_id: str,
        session: AsyncSession,
    ) -> User | None:
        stmt = select(User).where(
            User.email == email,
            User.tenant_id == tenant_id,
            User.is_active == True,  # noqa: E712
        )
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            return None
        if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            return None
        return user

    def create_access_token(self, user: User) -> str:
        expire = datetime.now(tz=UTC) + timedelta(minutes=self._access_expire)
        payload = {
            "sub": str(user.id),
            "tenant_id": user.tenant_id,
            "roles": user.roles,
            "type": "access",
            "exp": expire,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def create_refresh_token(self, user: User) -> str:
        expire = datetime.now(tz=UTC) + timedelta(days=self._refresh_expire)
        payload = {
            "sub": str(user.id),
            "tenant_id": user.tenant_id,
            "type": "refresh",
            "exp": expire,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def verify_token(self, token: str) -> TokenPayload:
        decoded = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        return TokenPayload(
            user_id=decoded["sub"],
            tenant_id=decoded["tenant_id"],
            roles=decoded.get("roles", []),
            token_type=decoded.get("type", "access"),
        )
