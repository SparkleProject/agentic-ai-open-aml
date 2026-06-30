"""Entity unwrapping API router (BE-304)."""

from typing import Any

from fastapi import APIRouter, Query

from aml.services.entity.resolver import OwnershipResolver
from aml.services.entity.risk_annotator import EntityRiskAnnotator

router = APIRouter(prefix="/entities", tags=["Entities"])


@router.get("/{entity_id}/ownership")
async def get_ownership(
    entity_id: str,
    jurisdiction: str = Query(default="AU"),  # noqa: ARG001
    max_depth: int = Query(default=5, ge=1, le=10),
) -> dict[str, Any]:
    resolver = OwnershipResolver()
    graph = await resolver.resolve(entity_id, max_depth=max_depth)

    annotator = EntityRiskAnnotator()
    graph = annotator.annotate(graph)

    return graph.model_dump()


@router.get("/{entity_id}/ubos")
async def get_ubos(entity_id: str) -> dict[str, Any]:
    resolver = OwnershipResolver()
    graph = await resolver.resolve(entity_id)

    return {
        "entity_id": entity_id,
        "ubos": [u.model_dump() for u in graph.ubos],
        "count": len(graph.ubos),
    }


@router.get("/search")
async def search_entities(
    name: str = Query(...),
    jurisdiction: str = Query(default="AU"),
) -> dict[str, Any]:
    from aml.services.entity.registry.mock import MockRegistryAdapter

    adapter = MockRegistryAdapter()
    results = await adapter.search(name, jurisdiction)
    return {"results": [r.model_dump() for r in results], "count": len(results)}
