"""Tests for model inventory and lifecycle (BE-405)."""

import pytest

from aml.services.model_registry.service import (
    ModelPurpose,
    ModelRegistryService,
    ModelStatus,
    RegisteredModel,
)


@pytest.fixture
def registry():
    svc = ModelRegistryService()
    svc.register(
        RegisteredModel(
            model_key="claude-reasoning",
            provider="bedrock",
            model_id="anthropic.claude-3-5-sonnet",
            purpose=ModelPurpose.REASONING,
            status=ModelStatus.ACTIVE,
        )
    )
    svc.register(
        RegisteredModel(
            model_key="titan-embed",
            provider="bedrock",
            model_id="amazon.titan-embed-text-v2",
            purpose=ModelPurpose.EMBEDDING,
            status=ModelStatus.ACTIVE,
        )
    )
    return svc


class TestModelRegistry:
    def test_register_and_get(self, registry):
        model = registry.get("claude-reasoning")
        assert model is not None
        assert model.provider == "bedrock"

    def test_get_active_by_purpose(self, registry):
        model = registry.get_active(ModelPurpose.REASONING)
        assert model is not None
        assert model.model_key == "claude-reasoning"

    def test_get_active_no_match(self, registry):
        assert registry.get_active(ModelPurpose.TRIAGE) is None

    def test_list_models_by_purpose(self, registry):
        result = registry.list_models(purpose=ModelPurpose.REASONING)
        assert len(result) == 1

    def test_list_models_by_status(self, registry):
        result = registry.list_models(status=ModelStatus.ACTIVE)
        assert len(result) == 2

    def test_list_all(self, registry):
        assert len(registry.list_models()) == 2


class TestModelLifecycle:
    def test_valid_transition(self):
        svc = ModelRegistryService()
        svc.register(
            RegisteredModel(
                model_key="new-model",
                provider="bedrock",
                model_id="test",
                purpose=ModelPurpose.REASONING,
            )
        )
        svc.transition("new-model", ModelStatus.VALIDATING)
        model = svc.get("new-model")
        assert model is not None
        assert model.status == ModelStatus.VALIDATING

    def test_invalid_transition_raises(self):
        svc = ModelRegistryService()
        svc.register(
            RegisteredModel(
                model_key="new-model",
                provider="bedrock",
                model_id="test",
            )
        )
        with pytest.raises(ValueError, match="Cannot transition"):
            svc.transition("new-model", ModelStatus.ACTIVE)

    def test_activate_deactivates_previous(self):
        svc = ModelRegistryService()
        svc.register(
            RegisteredModel(
                model_key="old",
                provider="bedrock",
                model_id="old",
                purpose=ModelPurpose.REASONING,
                status=ModelStatus.ACTIVE,
            )
        )
        svc.register(
            RegisteredModel(
                model_key="new",
                provider="bedrock",
                model_id="new",
                purpose=ModelPurpose.REASONING,
                status=ModelStatus.APPROVED,
            )
        )
        svc.transition("new", ModelStatus.ACTIVE)

        assert svc.get("old").status == ModelStatus.DEPRECATED
        assert svc.get("new").status == ModelStatus.ACTIVE
        assert svc.get_active(ModelPurpose.REASONING).model_key == "new"

    def test_deprecate_with_replacement(self):
        svc = ModelRegistryService()
        svc.register(
            RegisteredModel(
                model_key="old",
                provider="bedrock",
                model_id="old",
                purpose=ModelPurpose.REASONING,
                status=ModelStatus.ACTIVE,
            )
        )
        svc.deprecate("old", replacement_key="new-model")

        model = svc.get("old")
        assert model.status == ModelStatus.DEPRECATED
        assert model.replacement_model_key == "new-model"

    def test_full_lifecycle(self):
        svc = ModelRegistryService()
        svc.register(
            RegisteredModel(
                model_key="m1",
                provider="bedrock",
                model_id="test",
            )
        )
        svc.transition("m1", ModelStatus.VALIDATING)
        svc.transition("m1", ModelStatus.APPROVED, approved_by="admin")
        svc.transition("m1", ModelStatus.ACTIVE)
        svc.transition("m1", ModelStatus.DEPRECATED)
        svc.transition("m1", ModelStatus.RETIRED)

        assert svc.get("m1").status == ModelStatus.RETIRED

    def test_retired_cannot_transition(self):
        svc = ModelRegistryService()
        svc.register(
            RegisteredModel(
                model_key="m1",
                provider="bedrock",
                model_id="test",
                status=ModelStatus.RETIRED,
            )
        )
        with pytest.raises(ValueError, match="Cannot transition"):
            svc.transition("m1", ModelStatus.ACTIVE)

    def test_not_found_raises(self):
        svc = ModelRegistryService()
        with pytest.raises(ValueError, match="not found"):
            svc.transition("nonexistent", ModelStatus.ACTIVE)
