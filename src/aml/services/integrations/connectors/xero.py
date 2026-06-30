from aml.services.integrations.protocol import CRMCustomer, CRMIntegration


class XeroIntegration(CRMIntegration):
    @property
    def provider_name(self) -> str:
        return "xero"

    async def pull_customers(self, tenant_id: str) -> list[CRMCustomer]:  # noqa: ARG002
        return [
            CRMCustomer(external_id="XERO-001", name="Mock Xero Contact", email="contact@xero.mock"),
        ]

    async def push_risk_score(
        self,
        tenant_id: str,  # noqa: ARG002
        external_id: str,  # noqa: ARG002
        score: int,  # noqa: ARG002
        flags: list[str],  # noqa: ARG002
    ) -> bool:
        return True
