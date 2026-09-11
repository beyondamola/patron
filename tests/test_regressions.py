import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from harness.collector import ContainerSnapshot, collect_disk_usage_percent, collect_recent_logs
from harness.incident import IncidentRegistry, ESCALATED
from harness.policy import validate_plan
from harness.runtime import PatronRuntime
from harness.verifier import verify_incident
from scenarios.audit_reader import find_incident_after
from scenarios.docker_utils import DockerClient, DockerResult, DockerError
from scenarios.patron_process import ManagedPatron


def test_audit_reader_returns_latest_complete_record(tmp_path):
    path = tmp_path / "audit.jsonl"
    record = {"incident_type": "X", "context_summary": {"resource": "x"}, "timestamps": {"updated_at": "2026-09-10T00:00:00+00:00"}}
    path.write_text(json.dumps({**record, "final_status": "OPEN"}) + "\n" + json.dumps({**record, "final_status": "RESOLVED"}) + '\n{"partial":')
    assert find_incident_after("X", "x", "2026-09-09T00:00:00+00:00", path)["final_status"] == "RESOLVED"


def test_escalation_survives_restart_without_retry(tmp_path):
    path = tmp_path / "state.json"
    registry = IncidentRegistry(path, cooldown_seconds=0)
    incident, _ = registry.get_or_open("x", "docker_container", "X", "failure")
    registry.mark_final(incident, ESCALATED)
    registry.persist()
    assert IncidentRegistry(path, cooldown_seconds=0).get_or_open("x", "docker_container", "X", "failure") == (None, False)


def test_missing_observation_does_not_resolve_incident(tmp_path):
    registry = IncidentRegistry(tmp_path / "state.json")
    incident, _ = registry.get_or_open("x", "docker_container", "CONTAINER_STOPPED", "stopped")
    runtime = PatronRuntime(registry=registry, collector=Mock(collect=Mock(return_value=ContainerSnapshot("x", False, False, "inspect_failed", {}))))
    assert runtime.process_once()["error"] == "inspect_failed"
    assert incident.status == "OPEN"


@pytest.mark.parametrize("plan", [None, [], {"decision": []}, {"decision": "delete"}])
def test_policy_denies_malformed_plans(plan):
    assert not validate_plan(plan, {"allowed_actions": ["restart_container"]}).allowed


def test_escalation_verifies_state_not_recommendation():
    assert not verify_incident("x", "CONTAINER_OOM_KILLED", "escalate").passed
    assert verify_incident("x", "CONTAINER_OOM_KILLED", "escalate", incident_status="ESCALATED").passed


def test_disk_path_is_not_shell_code(monkeypatch):
    run = Mock(return_value=Mock(returncode=0, stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\ntmpfs 100 95 5 95% /data\n"))
    monkeypatch.setattr("harness.collector.docker_run", run)
    assert collect_disk_usage_percent("x", "/data; touch /tmp/unsafe") == 95
    assert run.call_args.args[0] == ["docker", "exec", "x", "df", "-P", "--", "/data; touch /tmp/unsafe"]


def test_stderr_application_logs_are_collected(monkeypatch):
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr("harness.collector.docker_run", Mock(return_value=Mock(returncode=0, stdout="", stderr=f"{stamp} CONFIG_ERROR invalid config\n")))
    assert collect_recent_logs("x", started_at=stamp) == ["CONFIG_ERROR invalid config"]


def test_network_cleanup_refuses_unrelated_network():
    docker = DockerClient()
    docker.run = Mock(return_value=DockerResult(0, '[{"Labels": {}}]', ""))
    with pytest.raises(DockerError, match="non-simulation network"):
        docker.remove_owned_network("user-network")
    assert docker.run.call_count == 1


def test_managed_patron_stops_with_sigint(tmp_path):
    import signal
    patron = ManagedPatron("x", "test", log_root=tmp_path)
    patron.process = Mock()
    patron.process.poll.return_value = None
    patron.stop()
    patron.process.send_signal.assert_called_once_with(signal.SIGINT)
    patron.process.wait.assert_called_once()
