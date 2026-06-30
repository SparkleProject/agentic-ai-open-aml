import enum
from dataclasses import dataclass, field


class Permission(enum.StrEnum):
    ALERT_VIEW = "alert:view"
    ALERT_INVESTIGATE = "alert:investigate"
    ALERT_OVERRIDE = "alert:override"
    CASE_VIEW = "case:view"
    CASE_ASSIGN = "case:assign"
    CASE_CLOSE = "case:close"
    REPORT_VIEW = "report:view"
    REPORT_DRAFT = "report:draft"
    REPORT_EDIT = "report:edit"
    REPORT_APPROVE = "report:approve"
    REPORT_SUBMIT = "report:submit"
    RULE_VIEW = "rule:view"
    RULE_CREATE = "rule:create"
    RULE_EDIT = "rule:edit"
    RULE_DELETE = "rule:delete"
    KYC_VIEW = "kyc:view"
    KYC_ONBOARD = "kyc:onboard"
    KYC_REVIEW = "kyc:review"
    AUDIT_VIEW = "audit:view"
    AUDIT_EXPORT = "audit:export"
    AUDIT_VERIFY = "audit:verify"
    USER_MANAGE = "user:manage"
    TENANT_CONFIGURE = "tenant:configure"
    PII_VIEW = "pii:view"


ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "admin": set(Permission),
    "compliance_officer": set(Permission) - {Permission.USER_MANAGE, Permission.TENANT_CONFIGURE},
    "analyst": {
        Permission.ALERT_VIEW,
        Permission.ALERT_INVESTIGATE,
        Permission.CASE_VIEW,
        Permission.CASE_ASSIGN,
        Permission.REPORT_VIEW,
        Permission.REPORT_DRAFT,
        Permission.REPORT_EDIT,
        Permission.RULE_VIEW,
        Permission.KYC_VIEW,
        Permission.KYC_ONBOARD,
        Permission.AUDIT_VIEW,
    },
    "auditor": {
        Permission.ALERT_VIEW,
        Permission.CASE_VIEW,
        Permission.REPORT_VIEW,
        Permission.RULE_VIEW,
        Permission.KYC_VIEW,
        Permission.AUDIT_VIEW,
        Permission.AUDIT_EXPORT,
        Permission.AUDIT_VERIFY,
        Permission.PII_VIEW,
    },
}


@dataclass
class AuthContext:
    user_id: str
    tenant_id: str
    roles: list[str] = field(default_factory=list)
    permissions: set[Permission] = field(default_factory=set)


class PermissionResolver:
    def resolve(self, user_id: str, tenant_id: str, roles: list[str]) -> AuthContext:
        permissions: set[Permission] = set()
        for role in roles:
            role_perms = ROLE_PERMISSIONS.get(role, set())
            permissions.update(role_perms)

        return AuthContext(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
            permissions=permissions,
        )

    @staticmethod
    def check(context: AuthContext, required: Permission) -> bool:
        return required in context.permissions

    @staticmethod
    def check_all(context: AuthContext, required: list[Permission]) -> bool:
        return all(p in context.permissions for p in required)

    @staticmethod
    def check_any(context: AuthContext, required: list[Permission]) -> bool:
        return any(p in context.permissions for p in required)
