# BE-104: Authentication & Authorization — Architecture & Implementation Plan

**Date:** 2026-06-30
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

The platform currently has no user authentication. All API endpoints accept a raw `X-Tenant-ID` header with no identity verification. The `PermissionResolver` (BE-404) defines 24 permissions and 4 roles but is never invoked. Any client can access any tenant's data.

BE-104 implements a **pluggable authentication system** using the Strategy pattern. It ships with built-in JWT authentication and is configurable to switch to AWS Cognito, Keycloak, or any OIDC provider via a single settings change.

## 2. Architecture: Pluggable Auth Provider (Strategy Pattern)

```
  Settings.auth_provider = "jwt" | "cognito" | "keycloak"
                │
  get_auth_provider(settings) ──> AuthProvider (ABC)
                                      │
                      ┌────────────────┼────────────────┐
                JWTAuthProvider   CognitoProvider   KeycloakProvider
                (built-in)        (future stub)     (future stub)
```

### Key Design Decisions

- **ABC, not Protocol**: `AuthProvider` is an ABC because we control all implementations and need explicit inheritance for type safety.
- **Session injection**: DB session is passed per-call, not held in the provider — keeps providers stateless and testable.
- **Backward compatibility**: Middleware falls back to `X-Tenant-ID` header when no JWT is present, so existing API consumers and tests continue working.
- **Soft permission enforcement**: Permission checks allow requests through when no auth context exists (migration period). Strict mode can be enabled via config.

### Dependencies on Existing Code

- `src/aml/services/auth/permissions.py` — `Permission` enum, `PermissionResolver`, `AuthContext` (BE-404, already implemented)
- `src/aml/api/middleware.py` — `TenantMiddleware` (extracts `X-Tenant-ID`)
- `src/aml/db/base.py` — `Base`, `TenantMixin`
- `src/aml/core/config.py` — `Settings`

## 3. Step-by-Step Implementation

### Step 1: User ORM Model
- `User(TenantMixin, Base)` with `email`, `password_hash`, `full_name`, `roles` (JSON), `is_active`

### Step 2: AuthProvider ABC + JWTAuthProvider
- `AuthProvider` ABC: `register()`, `authenticate()`, `create_access_token()`, `create_refresh_token()`, `verify_token()`
- `JWTAuthProvider`: bcrypt password hashing, PyJWT token creation/validation
- `get_auth_provider(settings)` factory

### Step 3: Auth Middleware
- Extract `Authorization: Bearer <token>`, verify via provider, populate `request.state.auth`
- Fall back to `X-Tenant-ID` for backward compatibility

### Step 4: Auth API Router
- `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`

### Step 5: Permission Wiring
- `require_permission()` FastAPI dependency applied to sensitive endpoints

### Step 6: Seed Admin User
- On startup, create `admin@aml.local` if no users exist

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| JWT secret leakage | Critical | Environment variable only. Rotate via config. |
| Breaking existing tests | High | Backward compat: X-Tenant-ID fallback. Tests unaffected. |
| Password brute force | Medium | Rate limiting (future). bcrypt cost factor = 12. |
| Token theft | Medium | Short-lived access tokens (30 min). Refresh token rotation. |
