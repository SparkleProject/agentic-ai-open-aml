"""Tests for data retention and privacy (BE-403)."""

from aml.services.privacy.retention import RetentionPolicyRegistry


class TestRetentionPolicyRegistry:
    def test_get_policy_au_transaction(self):
        registry = RetentionPolicyRegistry()
        policy = registry.get_policy("transaction", "AU")
        assert policy is not None
        assert policy.retention_days == 2555
        assert "AUSTRAC" in policy.legal_basis

    def test_get_policy_nz_customer(self):
        registry = RetentionPolicyRegistry()
        policy = registry.get_policy("customer", "NZ")
        assert policy is not None
        assert policy.retention_days == 1825

    def test_get_policy_unknown_returns_none(self):
        registry = RetentionPolicyRegistry()
        assert registry.get_policy("nonexistent", "AU") is None

    def test_tenant_override(self):
        registry = RetentionPolicyRegistry(tenant_overrides={"transaction": 3650})
        policy = registry.get_policy("transaction", "AU")
        assert policy is not None
        assert policy.retention_days == 3650

    def test_list_policies_by_jurisdiction(self):
        registry = RetentionPolicyRegistry()
        au_policies = registry.list_policies("AU")
        nz_policies = registry.list_policies("NZ")
        assert len(au_policies) >= 3
        assert len(nz_policies) >= 2
        assert all(p.jurisdiction == "AU" for p in au_policies)

    def test_list_all_policies(self):
        registry = RetentionPolicyRegistry()
        all_policies = registry.list_policies()
        assert len(all_policies) >= 5

    def test_grace_period_default(self):
        registry = RetentionPolicyRegistry()
        policy = registry.get_policy("transaction", "AU")
        assert policy is not None
        assert policy.grace_period_days == 30
