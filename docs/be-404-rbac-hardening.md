# BE-404: Role-Based Access Control Hardening — Architecture & Implementation Plan

**Date:** 2026-06-28
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

Phase 1 (BE-104) established basic authentication with JWT and four roles: Admin, Compliance Officer, Analyst, Auditor. BE-404 hardens this into a **fine-grained Attribute-Based Access Control (ABAC)** system layered on top of RBAC.

The platform now has capabilities that require granular permissions:
- Who can **approve** a SAR for submission (vs. who can only draft one)?
- Who can **override** an AI agent's recommendation?
- Who can **view** PII vs. seeing only redacted data?
- Who can **modify** monitoring rules vs. only viewing them?
- Who can **export** audit trails for regulatory submission?

### Dependencies on Existing Code
- `src/aml/api/middleware.py` — `TenantMiddleware` (extracts `X-Tenant-ID`).
- `src/aml/core/context.py` — tenant context management.
- `src/aml/core/config.py` — settings for auth provider.
- All API routers — will need permission checks.

---

## 2. Architecture Approach: RBAC + ABAC Hybrid

```
  Request ──> Auth Middleware (JWT) ──> Permission Resolver ──> Route Handler
                    │                        │
               Extract User             Evaluate:
               + Roles                  - Role permissions (RBAC)
               + Tenant                 - Resource attributes (ABAC)
                                        - Tenant-level overrides
```

---

## 3. Step-by-Step Implementation Roadmap

### Step 1: Define Permission Model

**Files:**
- `src/aml/services/auth/permissions.py`

**Implementation Details:**
- Define permission enum covering all platform operations:
  ```python
  class Permission(StrEnum):
      # Alerts
      ALERT_VIEW = "alert:view"
      ALERT_INVESTIGATE = "alert:investigate"
      ALERT_OVERRIDE = "alert:override"
      # Cases
      CASE_VIEW = "case:view"
      CASE_ASSIGN = "case:assign"
      CASE_CLOSE = "case:close"
      # Reports
      REPORT_VIEW = "report:view"
      REPORT_DRAFT = "report:draft"
      REPORT_EDIT = "report:edit"
      REPORT_APPROVE = "report:approve"
      REPORT_SUBMIT = "report:submit"
      # Rules
      RULE_VIEW = "rule:view"
      RULE_CREATE = "rule:create"
      RULE_EDIT = "rule:edit"
      RULE_DELETE = "rule:delete"
      # KYC
      KYC_VIEW = "kyc:view"
      KYC_ONBOARD = "kyc:onboard"
      KYC_REVIEW = "kyc:review"
      # Governance
      AUDIT_VIEW = "audit:view"
      AUDIT_EXPORT = "audit:export"
      AUDIT_VERIFY = "audit:verify"
      # Admin
      USER_MANAGE = "user:manage"
      TENANT_CONFIGURE = "tenant:configure"
      PII_VIEW = "pii:view"
  ```
- Define default role-permission mappings:
  - **Admin**: all permissions.
  - **Compliance Officer**: all except `USER_MANAGE`, `TENANT_CONFIGURE`.
  - **Analyst**: view + investigate + draft + edit. Cannot approve, submit, or manage rules.
  - **Auditor**: read-only: `*:view`, `AUDIT_*`, `PII_VIEW`.
- Tenants can customise role-permission mappings via `tenant.settings["rbac_overrides"]`.

**Why:** Moving from 4 coarse roles to fine-grained permissions prevents over-privileging. An analyst should be able to draft a SAR narrative but not submit it to AUSTRAC. Separation of duties is a regulatory requirement.

### Step 2: Implement Permission Resolver and Auth Context

**Files:**
- `src/aml/services/auth/resolver.py`
- `src/aml/services/auth/context.py`

**Implementation Details:**
- `AuthContext` data class:
  - `user_id: str`, `tenant_id: str`, `roles: list[str]`, `permissions: set[Permission]`, `attributes: dict[str, Any]`.
- `PermissionResolver`:
  - `resolve(user_id: str, tenant_id: str, jwt_claims: dict) -> AuthContext`:
    - Extracts roles from JWT claims.
    - Loads default permissions for each role.
    - Applies tenant-level RBAC overrides.
    - Returns the resolved `AuthContext` with the full permission set.
  - `check(context: AuthContext, required: Permission) -> bool`:
    - Returns `True` if the user has the required permission.
  - `check_all(context: AuthContext, required: list[Permission]) -> bool`:
    - Returns `True` if the user has ALL required permissions.
  - `check_any(context: AuthContext, required: list[Permission]) -> bool`:
    - Returns `True` if the user has ANY of the required permissions.

**Why:** The resolver centralises permission logic. Evaluating permissions at the service layer (not just the route) enables consistent enforcement even for internal service-to-service calls.

### Step 3: Build Permission Enforcement Middleware and Decorators

**Files:**
- `src/aml/api/middleware.py` (update)
- `src/aml/services/auth/decorators.py`

**Implementation Details:**
- Update `TenantMiddleware` to also:
  - Extract and validate the JWT from the `Authorization` header.
  - Resolve permissions via `PermissionResolver`.
  - Attach `AuthContext` to the request state (`request.state.auth`).
- Create `require_permission` FastAPI dependency:
  ```python
  def require_permission(*perms: Permission):
      async def dependency(request: Request):
          auth = request.state.auth
          if not resolver.check_all(auth, list(perms)):
              raise HTTPException(403, "Insufficient permissions")
          return auth
      return Depends(dependency)
  ```
- Usage in routers:
  ```python
  @router.post("/reports/{id}/submit")
  async def submit_report(id: str, auth: AuthContext = require_permission(Permission.REPORT_SUBMIT)):
      ...
  ```

**Why:** Declarative permission enforcement at the route level is clean and auditable. The dependency injection pattern means permissions are checked before the handler executes — no chance of forgetting a check inside business logic.

### Step 4: Apply Permissions to All Existing Routers

**Files:**
- `src/aml/api/routers/agents.py` (update)
- `src/aml/api/routers/alerts.py` (update)
- `src/aml/api/routers/rag.py` (update)
- `src/aml/api/routers/reports.py` (update from BE-301)
- `src/aml/api/routers/rules.py` (update from BE-305)
- `src/aml/api/routers/kyc.py` (update from BE-302)
- `src/aml/api/routers/governance.py` (update from BE-402)

**Implementation Details:**
- Add `require_permission(...)` dependency to every endpoint:
  - GET endpoints: require `*_VIEW` permission.
  - POST/PUT endpoints: require the appropriate write permission.
  - DELETE endpoints: require `*_DELETE` permission.
  - Sensitive endpoints: require specific high-privilege permissions (e.g., `REPORT_SUBMIT`, `AUDIT_EXPORT`).
- PII filtering: when `PII_VIEW` is NOT in the user's permissions, responses are automatically run through the `PIIRedactor` (BE-401).

**Why:** Every existing endpoint currently has no auth enforcement beyond the tenant header. This step retrofits granular access control to the entire API surface.

### Step 5: Create User Management API

**Files:**
- `src/aml/api/routers/users.py`

**Implementation Details:**
- `GET /api/v1/users` — List users in the tenant with their roles.
- `POST /api/v1/users` — Create/invite a user with specified roles.
- `PUT /api/v1/users/{user_id}/roles` — Update a user's roles.
- `GET /api/v1/users/{user_id}/permissions` — View resolved permissions for a user.
- `GET /api/v1/rbac/roles` — List all roles and their default permissions.
- `PUT /api/v1/rbac/roles/{role}/permissions` — Customise permissions for a role (tenant-level override).
- All user management endpoints require `USER_MANAGE` permission.
- Register in `app.py`.

**Why:** The FE `UserManagement.tsx` page needs these endpoints. Tenant admins must be able to manage users and customise role permissions without platform-level changes.

### Step 6: Implement Tests

**Files:**
- `tests/test_rbac.py`

**Implementation Details:**
- Test default role-permission mappings: verify each role has exactly the expected permissions.
- Test permission enforcement: attempt restricted operations with insufficient permissions → verify 403.
- Test tenant-level overrides: modify a role's permissions for a tenant, verify the override takes effect.
- Test PII filtering: request a customer endpoint without `PII_VIEW` → verify PII is redacted.
- Test separation of duties: analyst cannot approve a report they drafted.

---

## 4. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Breaking existing API consumers** when auth is enforced | High | Phased rollout: log permission violations first (warn mode), then enforce. |
| **Over-restricting access** blocks legitimate operations | Medium | Permissive defaults per role. Tenant admins can adjust. |
| **JWT secret compromise** | Critical | Short-lived tokens (15 min). Refresh token rotation. Secret rotation capability. |
| **Permission drift** as new endpoints are added | Medium | CI check: every route must have a `require_permission` dependency. |
