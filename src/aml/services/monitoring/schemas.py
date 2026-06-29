from typing import Any

from pydantic import BaseModel, Field, field_validator

from aml.db.models.alert import AlertSeverity

VALID_OPERATORS = {"gt", "gte", "lt", "lte", "eq", "in", "contains"}


class RuleCondition(BaseModel):
    field: str
    operator: str
    value: Any

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        if v not in VALID_OPERATORS:
            raise ValueError(f"Invalid operator '{v}'. Must be one of: {VALID_OPERATORS}")
        return v


class MonitoringRule(BaseModel):
    id: str
    name: str
    description: str
    conditions: list[RuleCondition]
    alert_type: str
    severity: AlertSeverity
    enabled: bool = True
    entity_type: str | None = None


class RuleMatch(BaseModel):
    rule_id: str
    rule_name: str
    alert_type: str
    severity: AlertSeverity
    matched_conditions: list[str] = Field(default_factory=list)
