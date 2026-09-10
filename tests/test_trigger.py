from harness.collector import ContainerSnapshot
from harness.trigger import (
    ContainerBadConfigTrigger,
    ContainerDependencyDownTrigger,
    ContainerDiskFullTrigger,
    ContainerHighCPUTrigger,
    ContainerOOMKilledTrigger,
    ContainerRestartLoopTrigger,
    ContainerStoppedTrigger,
    ContainerUnhealthyTrigger,
    default_trigger_registry,
)


def test_container_stopped_trigger_matches_exited_container() -> None:
    snapshot = ContainerSnapshot("mvp-nginx", exists=True, running=False, status="exited", raw={})
    trigger = ContainerStoppedTrigger()

    assert trigger.evaluate(snapshot)
    assert trigger.build_packet(snapshot)["incident_type"] == "CONTAINER_STOPPED"


def test_container_unhealthy_trigger_matches_running_unhealthy_container() -> None:
    snapshot = ContainerSnapshot(
        "mvp-nginx",
        exists=True,
        running=True,
        status="running",
        raw={},
        health="unhealthy",
        has_healthcheck=True,
    )
    trigger = ContainerUnhealthyTrigger()

    assert trigger.evaluate(snapshot)
    assert trigger.build_packet(snapshot)["incident_type"] == "CONTAINER_UNHEALTHY"


def test_container_unhealthy_trigger_does_not_match_missing_healthcheck() -> None:
    snapshot = ContainerSnapshot(
        "mvp-nginx",
        exists=True,
        running=True,
        status="running",
        raw={},
        health=None,
        has_healthcheck=False,
    )

    assert not ContainerUnhealthyTrigger().evaluate(snapshot)


def test_container_restart_loop_trigger_matches_restarting_container() -> None:
    snapshot = ContainerSnapshot(
        "mvp-nginx",
        exists=True,
        running=False,
        status="restarting",
        raw={"Restarting": True},
        exit_code=1,
        restart_count=3,
    )
    trigger = ContainerRestartLoopTrigger()

    assert trigger.evaluate(snapshot)
    assert trigger.build_packet(snapshot)["incident_type"] == "CONTAINER_RESTART_LOOP"


def test_registry_returns_first_matching_trigger() -> None:
    snapshot = ContainerSnapshot(
        "mvp-nginx",
        exists=True,
        running=False,
        status="restarting",
        raw={"Restarting": True},
        restart_count=3,
    )

    packet = default_trigger_registry().evaluate(snapshot)

    assert packet is not None
    assert packet["incident_type"] == "CONTAINER_RESTART_LOOP"


def test_restart_loop_threshold_prevents_stopped_fallthrough() -> None:
    snapshot = ContainerSnapshot(
        "mvp-nginx",
        exists=True,
        running=False,
        status="restarting",
        raw={"Restarting": True},
        restart_count=2,
    )

    assert default_trigger_registry().evaluate(snapshot) is None


def test_registry_returns_none_for_healthy_running_container() -> None:
    snapshot = ContainerSnapshot(
        "mvp-nginx",
        exists=True,
        running=True,
        status="running",
        raw={},
        health="healthy",
    )

    assert default_trigger_registry().evaluate(snapshot) is None


def test_new_resource_triggers_match_expected_metrics() -> None:
    assert ContainerOOMKilledTrigger().evaluate(
        ContainerSnapshot("x", True, False, "exited", {}, oom_killed=True)
    )
    assert ContainerHighCPUTrigger().evaluate(
        ContainerSnapshot("x", True, True, "running", {}, cpu_percent=90.0)
    )
    assert ContainerDiskFullTrigger().evaluate(
        ContainerSnapshot("x", True, True, "running", {}, disk_usage_percent=95.0)
    )
    assert ContainerBadConfigTrigger().evaluate(
        ContainerSnapshot("x", True, False, "exited", {}, error_patterns=["bad_config"])
    )
    assert ContainerDependencyDownTrigger().evaluate(
        ContainerSnapshot("x", True, True, "running", {}, dependency_status="down")
    )


def test_trigger_priority_prefers_bad_config_over_stopped() -> None:
    packet = default_trigger_registry().evaluate(
        ContainerSnapshot("x", True, False, "exited", {}, error_patterns=["bad_config"])
    )

    assert packet is not None
    assert packet["incident_type"] == "CONTAINER_BAD_CONFIG"
