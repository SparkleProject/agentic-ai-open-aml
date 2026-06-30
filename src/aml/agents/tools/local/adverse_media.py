import json
from typing import Any

from pydantic import BaseModel, Field

from aml.agents.tools.protocol import BaseTool


class AdverseMediaInput(BaseModel):
    entity_name: str = Field(description="Name of the person or entity to scan.")
    jurisdiction: str | None = Field(default=None, description="ISO country code.")


class AdverseMediaTool(BaseTool):
    @property
    def name(self) -> str:
        return "AdverseMediaTool"

    @property
    def description(self) -> str:
        return "Scans public and news sources for adverse media mentions of an entity."

    @property
    def input_schema(self) -> dict[str, Any]:
        return AdverseMediaInput.model_json_schema()

    async def execute(self, params: dict[str, Any]) -> str:
        validated = AdverseMediaInput(**params)

        if "criminal" in validated.entity_name.lower():
            return json.dumps(
                {
                    "findings": [
                        {
                            "source": "Mock News Agency",
                            "headline": f"Investigation into {validated.entity_name}",
                            "date": "2026-01-15",
                            "severity": 4,
                            "relevance_score": 0.85,
                        }
                    ]
                }
            )

        return json.dumps({"findings": []})
