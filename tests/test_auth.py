"""Tests for authentication and authorization (BE-104)."""
# ruff: noqa: S105, S106, B017, RUF012

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aml.db.base import Base
from aml.db.models.tenant import Tenant
from aml.db.models.user import User
from aml.services.auth.factory import get_auth_provider
from aml.services.auth.jwt_provider import JWTAuthProvider


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _make_tenant(db_session, slug="auth-test") -> str:
    tenant_id = str(uuid.uuid4())
    tenant = Tenant(id=uuid.UUID(tenant_id), name="Auth Test", slug=slug)
    db_session.add(tenant)
    await db_session.flush()
    return tenant_id


def _jwt_provider() -> JWTAuthProvider:
    return JWTAuthProvider(secret_key="test-secret", access_token_expire_minutes=5)


class TestUserModel:
    async def test_create_user(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session)
        user = User(
            tenant_id=tenant_id,
            email="test@example.com",
            password_hash="hashed",
            full_name="Test User",
            roles=["analyst"],
        )
        db_session.add(user)
        await db_session.commit()

        assert user.id is not None
        assert user.is_active is True
        assert user.roles == ["analyst"]

    async def test_user_defaults(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session, slug="auth-defaults")
        user = User(
            tenant_id=tenant_id,
            email="default@test.com",
            password_hash="hash",
            full_name="Default",
            roles=[],
        )
        db_session.add(user)
        await db_session.commit()
        assert user.is_active is True


class TestJWTAuthProvider:
    async def test_register(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session, slug="jwt-reg")
        provider = _jwt_provider()
        user = await provider.register(
            email="new@test.com",
            password="secure123",
            full_name="New User",
            tenant_id=tenant_id,
            roles=["analyst"],
            session=db_session,
        )
        assert user.email == "new@test.com"
        assert user.password_hash != "secure123"

    async def test_authenticate_success(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session, slug="jwt-auth-ok")
        provider = _jwt_provider()
        await provider.register(
            email="auth@test.com",
            password="pass123",
            full_name="Auth",
            tenant_id=tenant_id,
            roles=["analyst"],
            session=db_session,
        )
        user = await provider.authenticate(
            email="auth@test.com",
            password="pass123",
            tenant_id=tenant_id,
            session=db_session,
        )
        assert user is not None
        assert user.email == "auth@test.com"

    async def test_authenticate_wrong_password(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session, slug="jwt-auth-bad")
        provider = _jwt_provider()
        await provider.register(
            email="bad@test.com",
            password="correct",
            full_name="Bad",
            tenant_id=tenant_id,
            roles=[],
            session=db_session,
        )
        user = await provider.authenticate(
            email="bad@test.com",
            password="wrong",
            tenant_id=tenant_id,
            session=db_session,
        )
        assert user is None

    async def test_authenticate_nonexistent_user(self, db_session: AsyncSession):
        tenant_id = await _make_tenant(db_session, slug="jwt-auth-none")
        provider = _jwt_provider()
        user = await provider.authenticate(
            email="ghost@test.com",
            password="x",
            tenant_id=tenant_id,
            session=db_session,
        )
        assert user is None

    def test_create_and_verify_access_token(self):
        provider = _jwt_provider()

        class FakeUser:
            id = uuid.uuid4()
            tenant_id = "t1"
            roles = ["admin"]

        token = provider.create_access_token(FakeUser())
        payload = provider.verify_token(token)

        assert payload.tenant_id == "t1"
        assert payload.roles == ["admin"]
        assert payload.token_type == "access"

    def test_create_and_verify_refresh_token(self):
        provider = _jwt_provider()

        class FakeUser:
            id = uuid.uuid4()
            tenant_id = "t1"
            roles = []

        token = provider.create_refresh_token(FakeUser())
        payload = provider.verify_token(token)
        assert payload.token_type == "refresh"

    def test_expired_token_raises(self):
        provider = JWTAuthProvider(secret_key="test", access_token_expire_minutes=-1)

        class FakeUser:
            id = uuid.uuid4()
            tenant_id = "t1"
            roles = []

        token = provider.create_access_token(FakeUser())
        with pytest.raises(Exception):
            provider.verify_token(token)

    def test_invalid_token_raises(self):
        provider = _jwt_provider()
        with pytest.raises(Exception):
            provider.verify_token("not.a.valid.token")


class TestAuthProviderFactory:
    def test_jwt_provider(self, test_settings):
        provider = get_auth_provider(test_settings)
        assert isinstance(provider, JWTAuthProvider)

    def test_unknown_provider_raises(self, test_settings):
        test_settings.auth_provider = "unknown"
        with pytest.raises(ValueError, match="Unknown"):
            get_auth_provider(test_settings)


class TestAuthAPI:
    async def test_register_and_login(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="API", slug="auth-api-1")
        db_session.add(tenant)
        await db_session.flush()

        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        reg_resp = client.post(
            "/api/v1/auth/register",
            json={"email": "api@test.com", "password": "pass123", "full_name": "API User"},
            headers={"X-Tenant-ID": tenant_id},
        )
        assert reg_resp.status_code == 201
        assert reg_resp.json()["email"] == "api@test.com"

        login_resp = client.post(
            "/api/v1/auth/login",
            json={"email": "api@test.com", "password": "pass123"},
            headers={"X-Tenant-ID": tenant_id},
        )
        assert login_resp.status_code == 200
        data = login_resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "api@test.com"

        client.app.dependency_overrides.clear()

    async def test_login_invalid_credentials(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="API", slug="auth-api-2")
        db_session.add(tenant)
        await db_session.flush()

        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@test.com", "password": "wrong"},
            headers={"X-Tenant-ID": tenant_id},
        )
        assert resp.status_code == 401

        client.app.dependency_overrides.clear()

    async def test_duplicate_register(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="API", slug="auth-api-3")
        db_session.add(tenant)
        await db_session.flush()

        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        body = {"email": "dup@test.com", "password": "pass", "full_name": "Dup"}
        client.post("/api/v1/auth/register", json=body, headers={"X-Tenant-ID": tenant_id})
        resp = client.post("/api/v1/auth/register", json=body, headers={"X-Tenant-ID": tenant_id})
        assert resp.status_code == 409

        client.app.dependency_overrides.clear()

    async def test_list_users(self, db_session, client: TestClient):
        tenant_id = str(uuid.uuid4())
        tenant = Tenant(id=uuid.UUID(tenant_id), name="API", slug="auth-api-4")
        db_session.add(tenant)
        await db_session.flush()

        from aml.db.session import get_db

        async def override_db():
            yield db_session

        client.app.dependency_overrides[get_db] = override_db

        client.post(
            "/api/v1/auth/register",
            json={"email": "u1@test.com", "password": "p", "full_name": "U1"},
            headers={"X-Tenant-ID": tenant_id},
        )

        resp = client.get("/api/v1/auth/users", headers={"X-Tenant-ID": tenant_id})
        assert resp.status_code == 200
        assert resp.json()["count"] >= 1

        client.app.dependency_overrides.clear()
