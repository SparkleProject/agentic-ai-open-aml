import json
from typing import Any

from pydantic import BaseModel, Field

from aml.agents.tools.protocol import BaseTool


class SanctionsInput(BaseModel):
    entity_name: str = Field(description="The exact name of the person or company to screen against global lists.")
    country: str | None = Field(default=None, description="Optional ISO country code for tighter fuzzy matching.")
    dob: str | None = Field(default=None, description="Optional YYYY-MM-DD Date of Birth.")


class SanctionsTool(BaseTool):
    """
    Mock Sanctions Checking Tool implementation.
    """

    @property
    def name(self) -> str:
        return "SanctionsScreeningTool"

    @property
    def description(self) -> str:
        return (
            "Checks global OFAC, UN, and EU sanction lists for an exact or fuzzy match "
            "against a given entity name. Returns matched lists or a 'No Match' response."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return SanctionsInput.model_json_schema()

    async def execute(self, params: dict[str, Any]) -> str:
        # 1. Pydantic Validate the unstructured dict from the LLM
        validated_input = SanctionsInput(**params)

        # 2. Mock business logic
        if "bin laden" in validated_input.entity_name.lower():
            return json.dumps({"match": True, "lists": ["UN", "OFAC"], "score": 99.9})

        return json.dumps({"match": False, "reason": "No entities found meeting similarity threshold."})


class PEPScreeningInput(BaseModel):
    person_name: str = Field(description="Full name of the individual to screen.")
    nationality: str | None = Field(default=None, description="Known nationality.")


class PEPScreeningTool(BaseTool):
    """
    Mock PEP Screening Tool implementation.
    """

    @property
    def name(self) -> str:
        return "PEPScreeningTool"

    @property
    def description(self) -> str:
        return "Checks if a given individual is currently identified as a Politically Exposed Person (PEP)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return PEPScreeningInput.model_json_schema()

    async def execute(self, params: dict[str, Any]) -> str:
        validated_input = PEPScreeningInput(**params)

        if "putin" in validated_input.person_name.lower():
            return json.dumps({"is_pep": True, "role": "Head of State", "country": "RU"})

        return json.dumps({"is_pep": False})
