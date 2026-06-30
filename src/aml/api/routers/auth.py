"""Authentication API router (BE-104)."""

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml.core.config import get_settings
from aml.db.models.user import User
from aml.db.session import get_db
from aml.services.auth.factory import get_auth_provider

router = APIRouter(prefix="/auth", tags=["Authentication"])


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    roles: list[str] = ["analyst"]


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    settings = get_settings()
    provider = get_auth_provider(settings)

    existing = await db.execute(select(User).where(User.email == body.email, User.tenant_id == x_tenant_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = await provider.register(
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        tenant_id=x_tenant_id,
        roles=body.roles,
        session=db,
    )

    return {
        "user_id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "tenant_id": user.tenant_id,
        "roles": user.roles,
    }


@router.post("/login")
async def login(
    body: LoginRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    settings = get_settings()
    provider = get_auth_provider(settings)

    user = await provider.authenticate(
        email=body.email,
        password=body.password,
        tenant_id=x_tenant_id,
        session=db,
    )
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return {
        "access_token": provider.create_access_token(user),
        "refresh_token": provider.create_refresh_token(user),
        "token_type": "bearer",
        "user": {
            "user_id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "roles": user.roles,
            "tenant_id": user.tenant_id,
        },
    }


@router.post("/refresh")
async def refresh(body: RefreshRequest) -> dict[str, Any]:
    settings = get_settings()
    provider = get_auth_provider(settings)

    try:
        payload = provider.verify_token(body.refresh_token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid refresh token: {e}") from e

    if payload.token_type != "refresh":  # noqa: S105
        raise HTTPException(status_code=401, detail="Not a refresh token")

    dummy_user = User.__new__(User)
    object.__setattr__(dummy_user, "id", payload.user_id)
    object.__setattr__(dummy_user, "tenant_id", payload.tenant_id)
    object.__setattr__(dummy_user, "roles", payload.roles)

    return {
        "access_token": provider.create_access_token(dummy_user),
        "token_type": "bearer",
    }


@router.get("/me")
async def get_current_user(request: Request) -> dict[str, Any]:
    auth = getattr(request.state, "auth", None)
    if not auth:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return {
        "user_id": auth.user_id,
        "tenant_id": auth.tenant_id,
        "roles": auth.roles,
    }


@router.get("/users")
async def list_users(
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")

    stmt = select(User).where(User.tenant_id == x_tenant_id, User.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    users = result.scalars().all()

    return {
        "users": [
            {
                "user_id": str(u.id),
                "email": u.email,
                "full_name": u.full_name,
                "roles": u.roles,
                "is_active": u.is_active,
            }
            for u in users
        ],
        "count": len(users),
    }
