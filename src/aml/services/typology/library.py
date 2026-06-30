from dataclasses import dataclass, field


@dataclass
class Typology:
    typology_id: str
    name: str
    description: str
    category: str
    risk_level: str = "MEDIUM"
    indicators: list[str] = field(default_factory=list)
    jurisdictions: list[str] = field(default_factory=list)
    source: str = "PLATFORM"
    status: str = "PUBLISHED"
    adopted_count: int = 0


class TypologyLibrary:
    def __init__(self) -> None:
        self._typologies: dict[str, Typology] = {}

    def add(self, typology: Typology) -> Typology:
        self._typologies[typology.typology_id] = typology
        return typology

    def get(self, typology_id: str) -> Typology | None:
        return self._typologies.get(typology_id)

    def search(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        jurisdiction: str | None = None,
    ) -> list[Typology]:
        results = list(self._typologies.values())
        if query:
            q = query.lower()
            results = [t for t in results if q in t.name.lower() or q in t.description.lower()]
        if category:
            results = [t for t in results if t.category == category]
        if jurisdiction:
            results = [t for t in results if jurisdiction in t.jurisdictions]
        return results

    def adopt(self, typology_id: str) -> Typology | None:
        t = self._typologies.get(typology_id)
        if t:
            t.adopted_count += 1
        return t

    def list_all(self) -> list[Typology]:
        return list(self._typologies.values())

    def get_trending(self, limit: int = 10) -> list[Typology]:
        return sorted(self._typologies.values(), key=lambda t: t.adopted_count, reverse=True)[:limit]
