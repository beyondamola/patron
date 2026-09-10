from __future__ import annotations

from .base import Scenario
from .docker_utils import docker_available
from .implementations.expanded import (
    BadConfigScenario,
    DependencyDownScenario,
    DiskFullScenario,
    HighCPUScenario,
    OOMKilledScenario,
)
from .implementations.restart_loop import RestartLoopScenario
from .implementations.stopped import StoppedContainerScenario
from .implementations.unhealthy import UnhealthyContainerScenario


class ScenarioRegistry:
    def __init__(self) -> None:
        self._scenarios: dict[str, Scenario] = {}

    def register(self, scenario: Scenario) -> None:
        self._scenarios[scenario.name] = scenario

    def get(self, name: str) -> Scenario:
        try:
            return self._scenarios[name]
        except KeyError as exc:
            raise KeyError(f"unknown scenario: {name}") from exc

    def all(self) -> list[Scenario]:
        return list(self._scenarios.values())

    def names(self) -> list[str]:
        return sorted(self._scenarios)


def default_registry() -> ScenarioRegistry:
    registry = ScenarioRegistry()
    registry.register(StoppedContainerScenario())
    registry.register(UnhealthyContainerScenario())
    registry.register(RestartLoopScenario())
    registry.register(OOMKilledScenario())
    registry.register(HighCPUScenario())
    registry.register(DiskFullScenario())
    registry.register(BadConfigScenario())
    registry.register(DependencyDownScenario())
    return registry


def scenario_support_line(scenario: Scenario) -> str:
    supported = "yes" if docker_available() else "no: Docker unavailable"
    return f"{scenario.name}\t{supported}\t{scenario.description}"
