from typing import Any

from aml.services.kyc.protocol import CheckResult, IdentityVerificationProvider, VerificationResult


class MockIdentityVerifier(IdentityVerificationProvider):
    async def verify_identity(
        self,
        *,
        name: str,
        customer_type: str,  # noqa: ARG002
        metadata: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> VerificationResult:
        return VerificationResult(
            verified=True,
            confidence=0.95,
            checks=[
                CheckResult(check_name="document_check", passed=True, details="Mock document verified"),
                CheckResult(check_name="identity_match", passed=True, details="Mock identity matched"),
            ],
            provider_ref=f"MOCK-{name[:8]}",
        )
