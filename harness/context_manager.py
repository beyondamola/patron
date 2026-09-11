from __future__ import annotations

from .collector import ContainerSnapshot
from .incident import Incident


def build_context(snapshot: ContainerSnapshot, incident: Incident, trigger_packet: dict) -> dict:
    """Build the incident context supplied to the planner."""

    return {
        "incident_id": incident.incident_id,
        "resource": snapshot.name,
        "resource_type": trigger_packet["resource_type"],
        "incident_type": trigger_packet["incident_type"],
        "observed_state": trigger_packet["observed_state"],
        "expected_state": trigger_packet["expected_state"],
        "restart_count": snapshot.restart_count,
        "health_status": snapshot.health or "none",
        "runtime_status": snapshot.status,
        "exit_code": snapshot.exit_code,
        "oom_killed": snapshot.oom_killed,
        "cpu_percent": snapshot.cpu_percent,
        "cpu_quota": snapshot.cpu_quota,
        "cpu_period": snapshot.cpu_period,
        "nano_cpus": snapshot.nano_cpus,
        "started_at": snapshot.started_at,
        "probe_errors": snapshot.probe_errors or {},
        "disk_usage_percent": snapshot.disk_usage_percent,
        "recent_logs": snapshot.recent_logs or [],
        "error_patterns": snapshot.error_patterns or [],
        "dependency_evidence": snapshot.dependency_status,
        "allowed_actions": ["restart_container", "escalate"],
        "risk_level": "high" if trigger_packet["incident_type"] != "CONTAINER_STOPPED" else "low",
        "trigger": {
            "incident_type": trigger_packet["incident_type"],
            "reason": trigger_packet["reason"],
            "metadata": trigger_packet["metadata"],
        },
        "attempts": incident.attempts,
    }
