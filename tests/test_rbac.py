"""Tests for RBAC hardening (BE-404)."""

from aml.services.auth.permissions import Permission, PermissionResolver


class TestPermissionResolver:
    def test_admin_has_all_permissions(self):
        resolver = PermissionResolver()
        ctx = resolver.resolve("admin-user", "t1", ["admin"])
        assert Permission.USER_MANAGE in ctx.permissions
        assert Permission.REPORT_SUBMIT in ctx.permissions
        assert len(ctx.permissions) == len(Permission)

    def test_analyst_cannot_approve_report(self):
        resolver = PermissionResolver()
        ctx = resolver.resolve("analyst-user", "t1", ["analyst"])
        assert Permission.REPORT_APPROVE not in ctx.permissions
        assert Permission.REPORT_SUBMIT not in ctx.permissions
        assert Permission.ALERT_VIEW in ctx.permissions

    def test_auditor_read_only(self):
        resolver = PermissionResolver()
        ctx = resolver.resolve("auditor-user", "t1", ["auditor"])
        assert Permission.AUDIT_EXPORT in ctx.permissions
        assert Permission.PII_VIEW in ctx.permissions
        assert Permission.RULE_CREATE not in ctx.permissions
        assert Permission.REPORT_EDIT not in ctx.permissions

    def test_compliance_officer_no_user_manage(self):
        resolver = PermissionResolver()
        ctx = resolver.resolve("co-user", "t1", ["compliance_officer"])
        assert Permission.REPORT_SUBMIT in ctx.permissions
        assert Permission.USER_MANAGE not in ctx.permissions

    def test_multiple_roles_combine(self):
        resolver = PermissionResolver()
        ctx = resolver.resolve("multi-user", "t1", ["analyst", "auditor"])
        assert Permission.ALERT_INVESTIGATE in ctx.permissions
        assert Permission.AUDIT_EXPORT in ctx.permissions

    def test_unknown_role_gives_no_permissions(self):
        resolver = PermissionResolver()
        ctx = resolver.resolve("unknown-user", "t1", ["nonexistent_role"])
        assert len(ctx.permissions) == 0

    def test_check_single_permission(self):
        resolver = PermissionResolver()
        ctx = resolver.resolve("user", "t1", ["analyst"])
        assert resolver.check(ctx, Permission.ALERT_VIEW) is True
        assert resolver.check(ctx, Permission.USER_MANAGE) is False

    def test_check_all_permissions(self):
        resolver = PermissionResolver()
        ctx = resolver.resolve("user", "t1", ["analyst"])
        assert resolver.check_all(ctx, [Permission.ALERT_VIEW, Permission.CASE_VIEW]) is True
        assert resolver.check_all(ctx, [Permission.ALERT_VIEW, Permission.USER_MANAGE]) is False

    def test_check_any_permissions(self):
        resolver = PermissionResolver()
        ctx = resolver.resolve("user", "t1", ["analyst"])
        assert resolver.check_any(ctx, [Permission.USER_MANAGE, Permission.ALERT_VIEW]) is True
        assert resolver.check_any(ctx, [Permission.USER_MANAGE, Permission.TENANT_CONFIGURE]) is False

    def test_auth_context_fields(self):
        resolver = PermissionResolver()
        ctx = resolver.resolve("user-123", "tenant-456", ["admin"])
        assert ctx.user_id == "user-123"
        assert ctx.tenant_id == "tenant-456"
        assert ctx.roles == ["admin"]
