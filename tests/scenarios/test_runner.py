from scenarios.base import InjectionResult, ObservationResult, Scenario, ScenarioContext
from scenarios.docker_utils import ContainerState
from scenarios.result import INJECTION_FAILED
from scenarios.runner import run_scenario
import json
from pathlib import Path
import pytest


class FakeDocker:
    def inspect(self, name):
        return ContainerState(name, True, True, "running", None, 0, 0, {})


class MemoryWriter:
    def __init__(self) -> None:
        self.results = []

    def write(self, result) -> None:
        self.results.append(result)


class UnconfirmedScenario(Scenario):
    name = "unconfirmed"
    description = "does not confirm injection"
    default_target = "mvp-nginx"

    def setup(self, context):
        return None

    def validate_preconditions(self, context):
        return None

    def inject(self, context):
        return InjectionResult(True, False, "2026-06-07T00:00:00+00:00", None)

    def observe(self, context, injection):
        return ObservationResult(False, False, None, None, "running")

    def cleanup(self, context):
        return None


class FailingAfterSetupScenario(Scenario):
    name = "failing"
    description = "fails during injection"
    default_target = "mvp-nginx"

    def __init__(self) -> None:
        self.cleaned = False

    def setup(self, context):
        return None

    def validate_preconditions(self, context):
        return None

    def inject(self, context):
        raise RuntimeError("boom")

    def observe(self, context, injection):
        return ObservationResult(False, False, None, None, "running")

    def cleanup(self, context):
        self.cleaned = True


def test_runner_marks_unconfirmed_injection_failed() -> None:
    writer = MemoryWriter()
    context = ScenarioContext(
        scenario_name="unconfirmed",
        target_container="mvp-nginx",
        docker=FakeDocker(),
        start_patron=False,
    )

    result = run_scenario(UnconfirmedScenario(), context, writer=writer)

    assert result.status == INJECTION_FAILED
    assert writer.results == [result]


def test_runner_cleans_up_after_exception() -> None:
    scenario = FailingAfterSetupScenario()
    context = ScenarioContext(
        scenario_name="failing",
        target_container="mvp-nginx",
        docker=FakeDocker(),
        start_patron=False,
    )

    result = run_scenario(scenario, context, writer=MemoryWriter())

    assert scenario.cleaned
    assert result.status == INJECTION_FAILED and result.error == "boom"


@pytest.mark.parametrize("phase,expected", [("setup", "SETUP_FAILED"), ("inject", "INJECTION_FAILED"),
                                           ("observe", "FAILED")])
def test_exceptions_keep_their_phase_and_primary_error(tmp_path, monkeypatch, phase, expected):
    from unittest.mock import Mock
    from scenarios.docker_utils import DockerError
    monkeypatch.chdir(tmp_path)
    scenario = FailingAfterSetupScenario()
    scenario.inject = Mock(return_value=InjectionResult(True, True, "2026-09-13T00:00:00+00:00", None))
    setattr(scenario, phase, Mock(side_effect=DockerError("primary failure")))
    scenario.cleanup = Mock(side_effect=RuntimeError("cleanup failure"))
    context = ScenarioContext("failing", "target", docker=FakeDocker(), start_patron=False)
    result = run_scenario(scenario, context, writer=MemoryWriter())
    assert result.status == expected
    assert result.error == "primary failure; cleanup failed: cleanup failure"
    scenario.cleanup.assert_called_once()


def test_failure_state_evidence_is_persisted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    context = ScenarioContext("unconfirmed", "target", docker=FakeDocker(), start_patron=False)
    run_scenario(UnconfirmedScenario(), context, MemoryWriter())
    evidence = Path("logs/scenarios") / context.scenario_id / "post-state.json"
    assert json.loads(evidence.read_text())["name"] == "target"


def test_result_not_announced_before_persistence(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    class FailingWriter:
        def write(self, result):
            raise OSError("audit disk unavailable")
    context = ScenarioContext("unconfirmed", "target", docker=FakeDocker(), start_patron=False, verbose=True)
    with pytest.raises(OSError):
        run_scenario(UnconfirmedScenario(), context, FailingWriter())
    assert "Result:" not in capsys.readouterr().out
