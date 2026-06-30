from typing import Any

from pydantic import BaseModel, Field


class Director(BaseModel):
    name: str
    role: str = "director"


class Shareholder(BaseModel):
    name: str
    entity_id: str | None = None
    ownership_percentage: float
    shareholder_type: str = "individual"


class CorporateEntity(BaseModel):
    entity_id: str
    name: str
    entity_type: str
    jurisdiction: str = "AU"
    status: str = "active"
    registration_date: str | None = None
    directors: list[Director] = Field(default_factory=list)
    shareholders: list[Shareholder] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class OwnershipEdge(BaseModel):
    source_id: str
    target_id: str
    ownership_percentage: float
    relationship_type: str = "direct_ownership"


class UBO(BaseModel):
    name: str
    entity_id: str
    effective_ownership: float
    path: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class OwnershipGraph(BaseModel):
    root_entity_id: str
    entities: dict[str, CorporateEntity] = Field(default_factory=dict)
    edges: list[OwnershipEdge] = Field(default_factory=list)
    ubos: list[UBO] = Field(default_factory=list)
    max_depth_reached: int = 0
    risk_summary: dict[str, Any] = Field(default_factory=dict)
