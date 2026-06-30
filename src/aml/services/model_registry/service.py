import enum
from dataclasses import dataclass, field
from typing import Any


class ModelPurpose(enum.StrEnum):
    REASONING = "reasoning"
    EMBEDDING = "embedding"
    TRIAGE = "triage"
    EVALUATION = "evaluation"
    NARRATIVE = "narrative"


class ModelStatus(enum.StrEnum):
    REGISTERED = "registered"
    VALIDATING = "validating"
    APPROVED = "approved"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


VALID_TRANSITIONS: dict[ModelStatus, set[ModelStatus]] = {
    ModelStatus.REGISTERED: {ModelStatus.VALIDATING},
    ModelStatus.VALIDATING: {ModelStatus.APPROVED, ModelStatus.REGISTERED},
    ModelStatus.APPROVED: {ModelStatus.ACTIVE},
    ModelStatus.ACTIVE: {ModelStatus.DEPRECATED},
    ModelStatus.DEPRECATED: {ModelStatus.RETIRED, ModelStatus.ACTIVE},
    ModelStatus.RETIRED: set(),
}


@dataclass
class RegisteredModel:
    model_key: str
    provider: str
    model_id: str
    model_version: str = ""
    purpose: ModelPurpose = ModelPurpose.REASONING
    status: ModelStatus = ModelStatus.REGISTERED
    performance_metrics: dict[str, Any] = field(default_factory=dict)
    configuration: dict[str, Any] = field(default_factory=dict)
    approved_by: str | None = None
    replacement_model_key: str | None = None


class ModelRegistryService:
    def __init__(self) -> None:
        self._models: dict[str, RegisteredModel] = {}

    def register(self, model: RegisteredModel) -> RegisteredModel:
        self._models[model.model_key] = model
        return model

    def get(self, model_key: str) -> RegisteredModel | None:
        return self._models.get(model_key)

    def get_active(self, purpose: ModelPurpose) -> RegisteredModel | None:
        for model in self._models.values():
            if model.purpose == purpose and model.status == ModelStatus.ACTIVE:
                return model
        return None

    def list_models(
        self,
        purpose: ModelPurpose | None = None,
        status: ModelStatus | None = None,
    ) -> list[RegisteredModel]:
        result = list(self._models.values())
        if purpose:
            result = [m for m in result if m.purpose == purpose]
        if status:
            result = [m for m in result if m.status == status]
        return result

    def transition(self, model_key: str, new_status: ModelStatus, *, approved_by: str | None = None) -> RegisteredModel:
        model = self._models.get(model_key)
        if not model:
            raise ValueError(f"Model '{model_key}' not found")

        valid = VALID_TRANSITIONS.get(model.status, set())
        if new_status not in valid:
            raise ValueError(f"Cannot transition from {model.status.value} to {new_status.value}")

        if new_status == ModelStatus.ACTIVE:
            current_active = self.get_active(model.purpose)
            if current_active and current_active.model_key != model_key:
                current_active.status = ModelStatus.DEPRECATED

        model.status = new_status
        if approved_by:
            model.approved_by = approved_by
        return model

    def deprecate(self, model_key: str, replacement_key: str | None = None) -> RegisteredModel:
        model = self.transition(model_key, ModelStatus.DEPRECATED)
        if replacement_key:
            model.replacement_model_key = replacement_key
        return model
