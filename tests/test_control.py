import json
from uuid import uuid4

import pytest

from harness.audit import AuditLogger
from harness.control import ControlRequest, IncidentControl, execute_request
from harness.incident import ESCALATED, IncidentRegistry
from harness.main import main
from harness.storage import StateConflict


def setup(tmp_path):
    registry = IncidentRegistry(tmp_path / "state.json")
    registry.audit_path = str(tmp_path / "audit.jsonl")
    incident, _ = registry.get_or_open("x", "docker_container", "CONTAINER_HIGH_CPU", "load", container_id="generation-1")
    registry.mark_final(incident, ESCALATED)
    registry.persist()
    return registry, incident, IncidentControl(registry)


def request(registry, incident, operation="acknowledge"):
    return ControlRequest(str(uuid4()), incident.incident_id, registry.revision,
                          operation, "Investigated", "operator", "2026-09-10T00:00:00+00:00")


def test_acknowledgment_preserves_status_and_attempts(tmp_path):
    registry, incident, control = setup(tmp_path)
    result = control.apply(request(registry, incident))
    assert result["status"] == "APPLIED"
    loaded = IncidentRegistry(registry.state_path).incidents["x"]
    assert (loaded.status, loaded.attempts, loaded.container_id) == (ESCALATED, 0, "generation-1")
    assert loaded.acknowledgment["reason"] == "Investigated"


def test_rearm_opens_one_linked_incident_and_preserves_history(tmp_path):
    registry, incident, control = setup(tmp_path)
    control.apply(request(registry, incident, "rearm"))
    assert incident.status == ESCALATED and incident.rearmed
    assert not control.incidents()[incident.incident_id]["suppressed"]
    new, created = registry.get_or_open("x", "docker_container", "CONTAINER_HIGH_CPU", "load", container_id="generation-1")
    assert created and new.predecessor_id == incident.incident_id
    assert registry.get_or_open("x", "docker_container", "CONTAINER_HIGH_CPU", "load")[0] is new
    assert control.incidents()[incident.incident_id]["status"] == ESCALATED


def test_stale_request_rejected(tmp_path):
    registry, incident, control = setup(tmp_path)
    stale = request(registry, incident, "rearm")
    control.apply(request(registry, incident))
    assert control.apply(stale)["status"] == "REJECTED"
    assert not incident.rearmed


def test_duplicate_request_is_idempotent_across_restart(tmp_path):
    registry, incident, control = setup(tmp_path)
    req = request(registry, incident)
    first = control.apply(req)
    revision = registry.revision
    restarted = IncidentControl(IncidentRegistry(registry.state_path))
    assert restarted.apply(req) == first
    assert restarted.registry.revision == revision
    assert len(list(open(registry.audit_path))) == 1


def test_audit_failure_leaves_pending_and_recovers(tmp_path, monkeypatch):
    registry, incident, control = setup(tmp_path)
    req = request(registry, incident, "rearm")
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(control.audit, "log", fail)
    with pytest.raises(OSError):
        control.apply(req)
    restarted = IncidentControl(IncidentRegistry(registry.state_path))
    assert restarted.request_result(req.request_id)["status"] == "PENDING_AUDIT"
    restarted.process_pending()
    assert restarted.request_result(req.request_id)["status"] == "APPLIED"
    assert restarted.registry.incidents["x"].rearmed


def test_dry_run_changes_no_files(tmp_path):
    registry, incident, control = setup(tmp_path)
    before = registry.state_path.read_bytes()
    result = execute_request(registry, "rearm", incident.incident_id, "test", "actor", dry_run=True)
    assert result["status"] == "DRY_RUN"
    assert registry.state_path.read_bytes() == before
    assert not control.inbox.exists() and not control.audit.path.exists()


def test_offline_cli_applies_and_shows_state(tmp_path, capsys):
    registry, incident, control = setup(tmp_path)
    assert main(["incidents", "acknowledge", incident.incident_id, "--reason", "test", "--state-path", str(registry.state_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "APPLIED"
    assert main(["incidents", "show", incident.incident_id, "--state-path", str(registry.state_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["incident"]["acknowledgment"]["reason"] == "test"


def test_live_owner_receives_pending_request(tmp_path):
    registry, incident, control = setup(tmp_path)
    with registry.lock.acquire():
        other = IncidentRegistry(registry.state_path)
        result = execute_request(other, "rearm", incident.incident_id, "test", "actor", timeout=0)
        assert result["status"] == "PENDING"
        assert not incident.rearmed
        control.process_pending()
        assert control.request_result(result["request_id"])["status"] == "APPLIED"
    assert incident.rearmed


def test_duplicate_id_cannot_change_action(tmp_path):
    registry, incident, control = setup(tmp_path)
    req = request(registry, incident)
    control.apply(req)
    with pytest.raises(StateConflict):
        execute_request(registry, "rearm", incident.incident_id, req.reason, req.actor, req.request_id)


def test_rearm_healthy_resource_does_not_create_incident(tmp_path):
    from unittest.mock import Mock
    from harness.collector import ContainerSnapshot
    from harness.runtime import PatronRuntime
    registry, incident, control = setup(tmp_path)
    control.apply(request(registry, incident, "rearm"))
    runtime = PatronRuntime(registry=registry, collector=Mock(collect=Mock(return_value=
        ContainerSnapshot("x", True, True, "running", {}, container_id="generation-1"))))
    executor = Mock()
    runtime.executor = executor
    assert not runtime.process_once()["triggered"]
    executor.execute.assert_not_called()
    assert registry.incidents["x"].incident_id == incident.incident_id


def test_offline_retry_flushes_pending_audit(tmp_path, monkeypatch):
    registry, incident, control = setup(tmp_path)
    req = request(registry, incident)
    def fail(*args):
        raise OSError("audit unavailable")
    monkeypatch.setattr(control.audit, "log", fail)
    with pytest.raises(OSError):
        control.apply(req)
    restarted = IncidentRegistry(registry.state_path)
    assert execute_request(restarted, req.operation, req.incident_id, req.reason, req.actor,
                           req.request_id)["status"] == "APPLIED"


def test_audit_write_then_crash_does_not_duplicate_event(tmp_path, monkeypatch):
    registry, incident, control = setup(tmp_path)
    req = request(registry, incident)
    original = control.audit.log
    def write_then_crash(event):
        original(event)
        raise OSError("interrupted after audit fsync")
    monkeypatch.setattr(control.audit, "log", write_then_crash)
    with pytest.raises(OSError):
        control.apply(req)
    restarted = IncidentControl(IncidentRegistry(registry.state_path))
    restarted.process_pending()
    assert restarted.request_result(req.request_id)["status"] == "APPLIED"
    assert len(control.audit.path.read_text().splitlines()) == 1


def test_resolved_audit_only_incident_can_be_acknowledged(tmp_path):
    from harness.runtime import PatronRuntime
    registry, incident, control = setup(tmp_path)
    registry.mark_resolved(incident)
    runtime = PatronRuntime(registry=registry, audit_logger=control.audit)
    control.audit.log(runtime._audit_record(incident, {"reason": "recovered"}, None, None, None, None))
    registry.persist()
    assert control.apply(request(registry, incident))["status"] == "APPLIED"
    assert control.incidents()[incident.incident_id]["acknowledgment"]["actor"] == "operator"
    assert not registry.incidents
    assert control.apply(request(registry, incident, "rearm"))["status"] == "REJECTED"


def test_operator_history_is_scoped_to_state_path(tmp_path):
    registry, incident, control = setup(tmp_path)
    control.apply(request(registry, incident))
    other = IncidentRegistry(tmp_path / "other-state.json")
    other.audit_path = registry.audit_path
    assert not IncidentControl(other).incidents()


def test_incomplete_audit_is_preserved_not_appended(tmp_path):
    audit = AuditLogger(tmp_path / "audit.jsonl")
    audit.path.write_text('{"partial":')
    with pytest.raises(ValueError, match="incomplete"):
        audit.log({"event": "test"})
    assert audit.path.read_text() == '{"partial":'


def test_live_dry_run_does_not_need_writer_lock(tmp_path):
    registry, incident, control = setup(tmp_path)
    with registry.lock.acquire():
        other = IncidentRegistry(registry.state_path)
        assert execute_request(other, "rearm", incident.incident_id, "test", "actor", dry_run=True)["status"] == "DRY_RUN"
        assert not control.inbox.exists()
    assert not incident.rearmed


def test_resubmit_pending_request_is_idempotent(tmp_path):
    registry, incident, control = setup(tmp_path)
    request_id = str(uuid4())
    with registry.lock.acquire():
        for _ in range(2):
            other = IncidentRegistry(registry.state_path)
            assert execute_request(other, "rearm", incident.incident_id, "test", "actor", request_id, timeout=0)["status"] == "PENDING"
        assert len(list(control.inbox.glob("*.json"))) == 1
        control.process_pending()
    assert len(control.audit.path.read_text().splitlines()) == 1


def test_old_generation_does_not_suppress_replacement(tmp_path):
    registry, incident, control = setup(tmp_path)
    registry.observe_generation("x", "generation-2")
    assert not control.incidents()[incident.incident_id]["suppressed"]
    assert control.apply(request(registry, incident, "rearm"))["status"] == "REJECTED"
    new, created = registry.get_or_open("x", "docker_container", "CONTAINER_HIGH_CPU", "load", container_id="generation-2")
    assert created and new.incident_id != incident.incident_id and new.predecessor_id is None


def test_unknown_legacy_generation_keeps_suppression(tmp_path):
    registry, incident, control = setup(tmp_path)
    incident.container_id = None
    registry.observe_generation("x", "generation-2")
    assert registry.get_or_open("x", "docker_container", "CONTAINER_HIGH_CPU", "load", container_id="generation-2") == (None, False)


def test_new_generation_does_not_inherit_resolved_cooldown(tmp_path):
    registry, incident, control = setup(tmp_path)
    registry.mark_resolved(incident)
    assert registry.in_cooldown("x", "generation-1")
    assert not registry.in_cooldown("x", "generation-2")


@pytest.mark.parametrize("field,value", [("control_results", {"bad": {}}),
    ("outbox", {"bad": {"event": "operator_control"}}), ("audit_path", 123),
    ("observed_generations", {"x": []})])
def test_corrupt_control_state_fails_without_modification(tmp_path, field, value):
    registry, incident, control = setup(tmp_path)
    payload = json.loads(registry.state_path.read_text())
    payload[field] = value
    original = json.dumps(payload)
    registry.state_path.write_text(original)
    with pytest.raises(ValueError):
        IncidentRegistry(registry.state_path)
    assert registry.state_path.read_text() == original


def test_two_queued_requests_have_explicit_durable_outcomes(tmp_path):
    registry, incident, control = setup(tmp_path)
    requests = [request(registry, incident) for _ in range(2)]
    for req in requests:
        control.submit(req)
    control.process_pending()
    statuses = [control.request_result(req.request_id)["status"] for req in requests]
    assert sorted(statuses) == ["APPLIED", "REJECTED"]
    assert not list(control.inbox.glob("*.json"))
    reloaded = IncidentControl(IncidentRegistry(registry.state_path))
    assert [reloaded.request_result(req.request_id)["status"] for req in requests] == statuses


def test_concurrent_producers_publish_independently(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    registry, incident, control = setup(tmp_path)
    requests = [request(registry, incident) for _ in range(16)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(control.submit, requests))
    assert {path.stem for path in control.inbox.glob("*.json")} == {req.request_id for req in requests}


def test_concurrent_duplicate_producers_preserve_one_request(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    registry, incident, control = setup(tmp_path)
    req = request(registry, incident)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(control.submit, [req] * 16))
    assert len(list(control.inbox.glob("*.json"))) == 1
