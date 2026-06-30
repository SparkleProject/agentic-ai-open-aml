from abc import ABC, abstractmethod

from aml.services.entity.models import CorporateEntity


class CompanyRegistryAdapter(ABC):
    @abstractmethod
    async def lookup(self, entity_id: str) -> CorporateEntity | None: ...

    @abstractmethod
    async def search(self, name: str, jurisdiction: str) -> list[CorporateEntity]: ...
