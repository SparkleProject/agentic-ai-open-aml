from aml.services.entity.models import CorporateEntity, Director, Shareholder
from aml.services.entity.registry.protocol import CompanyRegistryAdapter

_MOCK_DATA: dict[str, CorporateEntity] = {
    "ACN-001": CorporateEntity(
        entity_id="ACN-001",
        name="HoldCo Pty Ltd",
        entity_type="company",
        jurisdiction="AU",
        directors=[Director(name="John Smith")],
        shareholders=[
            Shareholder(
                name="SubCo Pty Ltd",
                entity_id="ACN-002",
                ownership_percentage=60.0,
                shareholder_type="company",
            ),
            Shareholder(name="Jane Doe", ownership_percentage=40.0, shareholder_type="individual"),
        ],
    ),
    "ACN-002": CorporateEntity(
        entity_id="ACN-002",
        name="SubCo Pty Ltd",
        entity_type="company",
        jurisdiction="AU",
        directors=[Director(name="Bob Jones")],
        shareholders=[
            Shareholder(name="Alice Williams", ownership_percentage=100.0, shareholder_type="individual"),
        ],
    ),
    "ACN-CIRCULAR-A": CorporateEntity(
        entity_id="ACN-CIRCULAR-A",
        name="CircularA",
        entity_type="company",
        jurisdiction="AU",
        shareholders=[
            Shareholder(
                name="CircularB",
                entity_id="ACN-CIRCULAR-B",
                ownership_percentage=50.0,
                shareholder_type="company",
            ),
        ],
    ),
    "ACN-CIRCULAR-B": CorporateEntity(
        entity_id="ACN-CIRCULAR-B",
        name="CircularB",
        entity_type="company",
        jurisdiction="AU",
        shareholders=[
            Shareholder(
                name="CircularA",
                entity_id="ACN-CIRCULAR-A",
                ownership_percentage=50.0,
                shareholder_type="company",
            ),
        ],
    ),
}


class MockRegistryAdapter(CompanyRegistryAdapter):
    async def lookup(self, entity_id: str) -> CorporateEntity | None:
        return _MOCK_DATA.get(entity_id)

    async def search(self, name: str, jurisdiction: str) -> list[CorporateEntity]:  # noqa: ARG002
        return [e for e in _MOCK_DATA.values() if name.lower() in e.name.lower()]
