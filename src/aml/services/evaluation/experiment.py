import enum
import random
from dataclasses import dataclass
from typing import Any


class ExperimentStatus(enum.StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class Experiment:
    name: str
    tenant_id: str
    variant_config: dict[str, Any]
    sample_rate: float = 0.5
    max_samples: int = 100
    status: ExperimentStatus = ExperimentStatus.DRAFT
    samples_collected: int = 0

    def should_shadow_run(self) -> bool:
        if self.status != ExperimentStatus.RUNNING:
            return False
        if self.samples_collected >= self.max_samples:
            return False
        return random.random() < self.sample_rate  # noqa: S311

    def record_sample(self) -> None:
        self.samples_collected += 1
        if self.samples_collected >= self.max_samples:
            self.status = ExperimentStatus.COMPLETED


@dataclass
class ExperimentResult:
    experiment_name: str
    production_output: dict[str, Any]
    variant_output: dict[str, Any]
    quality_delta: float = 0.0


class ExperimentManager:
    def __init__(self) -> None:
        self._experiments: dict[str, Experiment] = {}

    def create(self, experiment: Experiment) -> Experiment:
        self._experiments[experiment.name] = experiment
        return experiment

    def get(self, name: str) -> Experiment | None:
        return self._experiments.get(name)

    def start(self, name: str) -> Experiment:
        exp = self._experiments.get(name)
        if not exp:
            raise ValueError(f"Experiment '{name}' not found")
        exp.status = ExperimentStatus.RUNNING
        return exp

    def pause(self, name: str) -> Experiment:
        exp = self._experiments.get(name)
        if not exp:
            raise ValueError(f"Experiment '{name}' not found")
        exp.status = ExperimentStatus.PAUSED
        return exp

    def list_experiments(self, tenant_id: str | None = None) -> list[Experiment]:
        if tenant_id:
            return [e for e in self._experiments.values() if e.tenant_id == tenant_id]
        return list(self._experiments.values())

    def get_active_for_tenant(self, tenant_id: str) -> Experiment | None:
        for exp in self._experiments.values():
            if exp.tenant_id == tenant_id and exp.status == ExperimentStatus.RUNNING:
                return exp
        return None
