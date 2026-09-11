from dataclasses import replace

import pytest

from harness.collector import ContainerSnapshot
from harness.verifier import verify_incident


class Clock:
    def __init__(self):
        self.offset = 0

    def monotonic(self):
        return self.offset

    def sleep(self, seconds):
        self.offset += seconds


def test_health_verifier_emits_every_read_with_recorded_clock(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("real time dependency used")

    monkeypatch.setattr("time.sleep", forbidden)
    monkeypatch.setattr("time.monotonic", forbidden)
    clock = Clock()
    initial = ContainerSnapshot("app", True, True, "running", {}, health="starting")
    snapshots = [initial, replace(initial, health="unhealthy"), replace(initial, health="healthy")]
    reads = iter(snapshots)
    observed = []
    result = verify_incident("app", "CONTAINER_UNHEALTHY", "restart_container",
        inspect_fn=lambda name: next(reads), clock=clock, wait_for_health=True,
        on_observation=lambda snapshot: observed.append((clock.offset, snapshot)))
    assert result.passed
    assert [offset for offset, _ in observed] == [0, 0.5, 1]
    assert [snapshot for _, snapshot in observed] == snapshots


def test_unhealthy_verification_is_bounded_without_real_sleep():
    clock = Clock()
    observed = []
    snapshot = ContainerSnapshot("app", True, True, "running", {}, health="unhealthy")
    result = verify_incident("app", "CONTAINER_UNHEALTHY", "restart_container",
        inspect_fn=lambda name: snapshot, clock=clock, wait_for_health=True,
        on_observation=observed.append)
    assert not result.passed and clock.offset == 8
    assert len(observed) == 17


def test_escalation_records_no_invented_docker_observation():
    def forbidden(*args, **kwargs):
        raise AssertionError("escalation must not inspect Docker")

    result = verify_incident("app", "CONTAINER_HIGH_CPU", "escalate",
        inspect_fn=forbidden, on_observation=forbidden, incident_status="ESCALATED")
    assert result.passed and result.health == "not_applicable"


def test_observation_sink_failure_is_not_silently_ignored():
    def fail(snapshot):
        raise OSError("capture disk full")

    with pytest.raises(OSError, match="capture disk full"):
        verify_incident("app", "CONTAINER_STOPPED", "restart_container",
            inspect_fn=lambda name: ContainerSnapshot(name, True, True, "running", {}),
            on_observation=fail)
