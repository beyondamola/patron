from scenarios.base import ScenarioContext
from scenarios.docker_utils import ContainerState
from scenarios.implementations.restart_loop import restart_threshold_crossed
from scenarios.implementations.stopped import StoppedContainerScenario
from scenarios.implementations.unhealthy import UnhealthyContainerScenario


class FakeDocker:
    def __init__(self, state: ContainerState) -> None:
        self.state = state

    def inspect(self, name: str) -> ContainerState:
        return self.state


def context_for(state: ContainerState, scenario_name: str = "test") -> ScenarioContext:
    return ScenarioContext(
        scenario_name=scenario_name,
        target_container=state.name,
        docker=FakeDocker(state),
    )


def test_stopped_scenario_confirms_exited_state() -> None:
    state = ContainerState("mvp-nginx", True, False, "exited", None, 0, 0, {})

    assert StoppedContainerScenario.failure_confirmed(context_for(state, "stopped"))


def test_unhealthy_scenario_distinguishes_unhealthy_from_stopped() -> None:
    unhealthy = ContainerState(
        "patron-unhealthy",
        True,
        True,
        "running",
        "unhealthy",
        0,
        0,
        {},
        has_healthcheck=True,
    )
    stopped = ContainerState("patron-unhealthy", True, False, "exited", None, 1, 0, {})

    assert UnhealthyContainerScenario.failure_confirmed(context_for(unhealthy, "unhealthy"))
    assert not UnhealthyContainerScenario.failure_confirmed(context_for(stopped, "unhealthy"))


def test_restart_loop_threshold_logic() -> None:
    below = ContainerState("patron-restart-loop", True, False, "restarting", None, 1, 2, {})
    at_threshold = ContainerState("patron-restart-loop", True, False, "restarting", None, 1, 3, {})

    assert not restart_threshold_crossed(below, threshold=3)
    assert restart_threshold_crossed(at_threshold, threshold=3)
