from typing import Any

from pydantic import BaseModel, field_validator

from aml.db.models.alert import AlertSeverity
from aml.services.monitoring.schemas import VALID_OPERATORS


class CreateRuleRequest(BaseModel):
    rule_id: str
    name: str
    description: str = ""
    conditions: list[dict[str, Any]]
    alert_type: str
    severity: AlertSeverity
    enabled: bool = True
    entity_type: str | None = None

    @field_validator("conditions")
    @classmethod
    def validate_conditions(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for cond in v:
            op = cond.get("operator")
            if op not in VALID_OPERATORS:
                raise ValueError(f"Invalid operator '{op}'. Must be one of: {VALID_OPERATORS}")
        return v


class UpdateRuleRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    conditions: list[dict[str, Any]] | None = None
    alert_type: str | None = None
    severity: AlertSeverity | None = None
    enabled: bool | None = None
    change_reason: str | None = None

    @field_validator("conditions")
    @classmethod
    def validate_conditions(cls, v: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if v is None:
            return v
        for cond in v:
            op = cond.get("operator")
            if op not in VALID_OPERATORS:
                raise ValueError(f"Invalid operator '{op}'. Must be one of: {VALID_OPERATORS}")
        return v
