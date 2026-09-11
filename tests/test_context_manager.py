from harness.collector import ContainerSnapshot
from harness.context_manager import build_context
from harness.incident import Incident
from harness.trigger import ContainerUnhealthyTrigger


def test_context_schema_is_generic_for_trigger_packet() -> None:
    snapshot = ContainerSnapshot(
        "mvp-nginx",
        exists=True,
        running=True,
        status="running",
        raw={},
        health="unhealthy",
    )
    trigger_packet = ContainerUnhealthyTrigger().build_packet(snapshot)
    incident = Incident.open(
        resource="mvp-nginx",
        resource_type="docker_container",
        incident_type=trigger_packet["incident_type"],
        trigger_reason=trigger_packet["reason"],
    )

    context = build_context(snapshot, incident, trigger_packet)

    assert set(context) == {
        "allowed_actions",
        "attempts",
        "expected_state",
        "exit_code",
        "oom_killed",
        "cpu_percent",
        "cpu_quota",
        "cpu_period",
        "nano_cpus",
        "started_at",
        "probe_errors",
        "disk_usage_percent",
        "error_patterns",
        "dependency_evidence",
        "health_status",
        "incident_id",
        "incident_type",
        "observed_state",
        "recent_logs",
        "restart_count",
        "resource",
        "resource_type",
        "risk_level",
        "runtime_status",
        "trigger",
    }
    assert context["incident_type"] == "CONTAINER_UNHEALTHY"
    assert context["observed_state"] == "unhealthy"
