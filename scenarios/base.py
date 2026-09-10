from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .docker_utils import DockerClient, simulation_labels


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ScenarioContext:
    scenario_name: str
    target_container: str
    timeout_seconds: int = 60
    keep_resources: bool = False
    verbose: bool = False
    trace: bool = False
    reset_simulation_state: bool = False
    start_patron: bool = True
    patron_interval: int = 1
    poll_interval_seconds: float = 1.0
    scenario_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: str = field(default_factory=utc_now)
    docker: DockerClient = field(default_factory=DockerClient)

    @property
    def labels(self) -> dict[str, str]:
        return simulation_labels(self.scenario_name, self.scenario_id)

    def narrate(self, message: str) -> None:
        if not (self.verbose or self.trace):
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[Scenario][{timestamp}] {message}")


@dataclass(frozen=True)
class InjectionResult:
    injected: bool
    observed: bool
    injected_at: str | None
    observed_at: str | None
    error: str | None = None


@dataclass(frozen=True)
class ObservationResult:
    detected: bool
    recovered: bool
    detected_at: str | None
    recovered_at: str | None
    final_state: str | None
    error: str | None = None
    patron_incident_id: str | None = None
    expected_incident_type: str | None = None
    observed_incident_type: str | None = None
    expected_final_status: str | None = None
    observed_final_status: str | None = None


class Scenario(ABC):
    name: str
    description: str
    default_target: str

    @abstractmethod
    def setup(self, context: ScenarioContext) -> None:
        raise NotImplementedError

    @abstractmethod
    def validate_preconditions(self, context: ScenarioContext) -> None:
        raise NotImplementedError

    @abstractmethod
    def inject(self, context: ScenarioContext) -> InjectionResult:
        raise NotImplementedError

    @abstractmethod
    def observe(self, context: ScenarioContext, injection: InjectionResult) -> ObservationResult:
        raise NotImplementedError

    @abstractmethod
    def cleanup(self, context: ScenarioContext) -> None:
        raise NotImplementedError

    def supported(self, context: ScenarioContext | None = None) -> bool:
        return True

    def details(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "default_target": self.default_target,
        }

    def create_environment(self, context: ScenarioContext) -> None:
        self.setup(context)

    def confirm_baseline(self, context: ScenarioContext) -> None:
        self.validate_preconditions(context)

    def confirm_injection(self, context: ScenarioContext, injection: InjectionResult) -> bool:
        return injection.observed

    def observe_outcome(self, context: ScenarioContext, injection: InjectionResult) -> ObservationResult:
        return self.observe(context, injection)
