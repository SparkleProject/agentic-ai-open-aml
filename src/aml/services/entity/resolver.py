from aml.services.entity.models import UBO, CorporateEntity, OwnershipEdge, OwnershipGraph
from aml.services.entity.registry.mock import MockRegistryAdapter
from aml.services.entity.registry.protocol import CompanyRegistryAdapter

UBO_THRESHOLD = 0.25


class OwnershipResolver:
    def __init__(self, *, registry: CompanyRegistryAdapter | None = None) -> None:
        self._registry = registry or MockRegistryAdapter()

    async def resolve(
        self,
        entity_id: str,
        *,
        max_depth: int = 5,
        ubo_threshold: float = UBO_THRESHOLD,
    ) -> OwnershipGraph:
        entities: dict[str, CorporateEntity] = {}
        edges: list[OwnershipEdge] = []
        ubos: list[UBO] = []
        visited: set[str] = set()

        await self._traverse(
            entity_id=entity_id,
            effective_ownership=1.0,
            path=[],
            depth=0,
            max_depth=max_depth,
            ubo_threshold=ubo_threshold,
            entities=entities,
            edges=edges,
            ubos=ubos,
            visited=visited,
            depth_tracker=[0],
        )

        return OwnershipGraph(
            root_entity_id=entity_id,
            entities=entities,
            edges=edges,
            ubos=ubos,
            max_depth_reached=len(visited),
        )

    async def _traverse(
        self,
        *,
        entity_id: str,
        effective_ownership: float,
        path: list[str],
        depth: int,
        max_depth: int,
        ubo_threshold: float,
        entities: dict[str, CorporateEntity],
        edges: list[OwnershipEdge],
        ubos: list[UBO],
        visited: set[str],
        depth_tracker: list[int],
    ) -> None:
        if entity_id in visited:
            if entity_id in entities:
                entities[entity_id].risk_flags.append("circular_ownership")
            return

        if depth > max_depth:
            return

        visited.add(entity_id)
        depth_tracker[0] = max(depth_tracker[0], depth)

        entity = await self._registry.lookup(entity_id)
        if not entity:
            return

        entities[entity_id] = entity

        for sh in entity.shareholders:
            child_effective = effective_ownership * (sh.ownership_percentage / 100.0)
            current_path = [*path, entity_id]

            if sh.entity_id:
                edges.append(
                    OwnershipEdge(
                        source_id=entity_id,
                        target_id=sh.entity_id,
                        ownership_percentage=sh.ownership_percentage,
                    )
                )
                await self._traverse(
                    entity_id=sh.entity_id,
                    effective_ownership=child_effective,
                    path=current_path,
                    depth=depth + 1,
                    max_depth=max_depth,
                    ubo_threshold=ubo_threshold,
                    entities=entities,
                    edges=edges,
                    ubos=ubos,
                    visited=visited,
                    depth_tracker=depth_tracker,
                )
            elif sh.shareholder_type == "individual" and child_effective >= ubo_threshold:
                ubos.append(
                    UBO(
                        name=sh.name,
                        entity_id=f"IND-{sh.name}",
                        effective_ownership=round(child_effective * 100, 2),
                        path=[*current_path, f"IND-{sh.name}"],
                    )
                )
