import json
from typing import Any

from pydantic import BaseModel, Field

from aml.agents.tools.protocol import BaseTool
from aml.services.entity.resolver import OwnershipResolver
from aml.services.entity.risk_annotator import EntityRiskAnnotator


class EntityUnwrapInput(BaseModel):
    entity_id: str = Field(description="Registry ID (e.g. ACN for ASIC).")
    jurisdiction: str = Field(default="AU", description="ISO country code.")


class EntityUnwrapTool(BaseTool):
    @property
    def name(self) -> str:
        return "EntityUnwrapTool"

    @property
    def description(self) -> str:
        return "Resolves corporate ownership structure, identifying UBOs and risk flags."

    @property
    def input_schema(self) -> dict[str, Any]:
        return EntityUnwrapInput.model_json_schema()

    async def execute(self, params: dict[str, Any]) -> str:
        try:
            validated = EntityUnwrapInput(**params)
        except Exception as e:
            return f"Error: invalid parameters — {e}"

        resolver = OwnershipResolver()
        graph = await resolver.resolve(validated.entity_id)

        annotator = EntityRiskAnnotator()
        graph = annotator.annotate(graph)

        return json.dumps(graph.model_dump(), default=str)
