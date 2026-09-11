from unittest.mock import Mock

import pytest

from harness.audit import AuditLogger
from harness.capture import CaptureError, read_capture
from harness.collector import ContainerSnapshot
from harness.incident import IncidentRegistry
from harness.runtime import PatronRuntime


def runtime(tmp_path, snapshot, **kwargs):
    return PatronRuntime(container_name="target", collector=Mock(collect=Mock(return_value=snapshot)),
        registry=IncidentRegistry(tmp_path / "state.json"),
        audit_logger=AuditLogger(tmp_path / "incidents.jsonl"),
        capture_path=tmp_path / "capture.jsonl", **kwargs)


def test_capture_success_contains_causal_stages_and_independent_verifier_read(tmp_path, monkeypatch):
    stopped = ContainerSnapshot("target", True, False, "exited", {}, container_id="generation")
    healthy = ContainerSnapshot("target", True, True, "running", {}, container_id="generation")
    monkeypatch.setattr("harness.verifier.DockerCollector", Mock(return_value=Mock(collect=Mock(return_value=healthy))))
    executor = Mock()
    executor.execute.return_value = {"action": "restart_container", "success": True}
    instance = runtime(tmp_path, stopped, executor=executor)
    assert instance.process_once()["incident"]["status"] == "RESOLVED"
    instance.finish_capture()
    records = read_capture(tmp_path / "capture.jsonl")
    events = [record["event"] for record in records]
    assert events == ["run_start", "cycle_start", "observation", "trigger", "transition",
        "context", "plan", "policy", "action_requested", "execution", "verification_observation",
        "verification", "transition", "cycle_end", "run_end"]
    primary = next(record for record in records if record["event"] == "observation")
    verification = next(record for record in records if record["event"] == "verification_observation")
    assert not primary["payload"]["snapshot"]["running"]
    assert verification["payload"]["snapshot"]["running"]
    assert verification["observation_id"] == primary["sequence"]
    assert verification["incident_id"]
    assert records[0]["payload"]["initial_state"]["incidents"] == {}


def test_healthy_and_failed_collection_are_both_recorded(tmp_path):
    instance = runtime(tmp_path, ContainerSnapshot("target", True, True, "running", {}))
    assert not instance.process_once()["triggered"]
    instance.collector.collect.return_value = ContainerSnapshot("target", False, False, "inspect_failed", {})
    assert instance.process_once()["error"] == "inspect_failed"
    instance.finish_capture()
    records = read_capture(tmp_path / "capture.jsonl")
    observations = [record for record in records if record["event"] == "observation"]
    assert len(observations) == 2
    assert not observations[1]["payload"]["snapshot"]["exists"]
    assert not any(record["event"] == "action_requested" for record in records)


def test_dry_run_captures_skipped_execution_and_never_requests_an_action(tmp_path):
    executor = Mock()
    instance = runtime(tmp_path, ContainerSnapshot("target", True, False, "exited", {}),
                       dry_run=True, executor=executor)
    instance.process_once()
    instance.finish_capture()
    records = read_capture(tmp_path / "capture.jsonl")
    executor.execute.assert_not_called()
    assert not any(record["event"] == "action_requested" for record in records)
    execution = next(record for record in records if record["event"] == "execution")
    assert execution["payload"]["result"]["reason"] == "dry_run"


def test_capture_failure_before_action_stops_execution(tmp_path, monkeypatch):
    executor = Mock()
    instance = runtime(tmp_path, ContainerSnapshot("target", True, False, "exited", {}), executor=executor)
    instance._start_capture()
    original = instance.capture.emit

    def emit(event, payload, **kwargs):
        if event == "action_requested":
            raise OSError("disk full")
        return original(event, payload, **kwargs)

    monkeypatch.setattr(instance.capture, "emit", emit)
    try:
        with pytest.raises(CaptureError, match="disk full"):
            instance.process_once()
    finally:
        instance.finish_capture(complete=False)
    executor.execute.assert_not_called()
    with pytest.raises(ValueError, match="missing run_end"):
        read_capture(tmp_path / "capture.jsonl")


def test_capture_cannot_share_audit_or_state_path(tmp_path):
    path = tmp_path / "state.json"
    with pytest.raises(ValueError, match="separate"):
        PatronRuntime(registry=IncidentRegistry(path), capture_path=path)


def test_queued_operator_request_has_before_and_after_capture(tmp_path):
    from uuid import uuid4
    from harness.control import ControlRequest, IncidentControl

    instance = runtime(tmp_path, ContainerSnapshot("target", True, False, "exited", {}, oom_killed=True),
        executor=Mock(execute=Mock(return_value={"action": "escalate", "success": True})))
    incident = instance.process_once()["incident"]
    request = ControlRequest(str(uuid4()), incident["incident_id"], instance.registry.revision,
        "acknowledge", "investigating", "tester", instance.clock.utc_now())
    IncidentControl(instance.registry, instance.audit_logger).submit(request)
    instance.process_once()
    instance.finish_capture()
    events = [record for record in read_capture(tmp_path / "capture.jsonl") if record["event"] == "control"]
    assert [record["payload"]["phase"] for record in events] == ["requested", "applied"]
    assert events[1]["payload"]["result"]["status"] == "APPLIED"
    assert events[1]["payload"]["state"]["incidents"]["target"]["acknowledgment"]["actor"] == "tester"
