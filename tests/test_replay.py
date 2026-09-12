import json
from unittest.mock import Mock
from datetime import datetime, timedelta, timezone

import pytest

from harness.audit import AuditLogger
from harness.capture import CaptureError
from harness.collector import ContainerSnapshot
from harness.incident import IncidentRegistry
from harness.replay import replay_capture
from harness.runtime import PatronRuntime


class FixtureClock:
    offset = 0

    def utc_now(self):
        return (datetime(2026, 9, 11, tzinfo=timezone.utc) + timedelta(seconds=self.offset)).isoformat()

    def monotonic(self):
        return self.offset

    def sleep(self, seconds):
        self.offset += seconds


def make_capture(tmp_path):
    path = tmp_path / "capture.jsonl"
    runtime = PatronRuntime(container_name="target", capture_path=path,
        collector=Mock(collect=Mock(return_value=ContainerSnapshot("target", True, False, "exited", {}, oom_killed=True))),
        registry=IncidentRegistry(tmp_path / "state.json"), audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        executor=Mock(execute=Mock(return_value={"action": "escalate", "success": True})))
    runtime.process_once()
    runtime.process_once()  # Persistent failure must remain suppressed.
    runtime.finish_capture()
    return path


def test_exact_replay_is_repeatable_and_has_no_live_adapters(tmp_path, monkeypatch):
    path = make_capture(tmp_path)
    originals = {p: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError("live dependency invoked during replay")

    for name in ("DockerCollector", "DockerExecutor"):
        monkeypatch.setattr(f"harness.runtime.{name}", forbidden)
    monkeypatch.setattr("time.sleep", forbidden)
    monkeypatch.setattr("time.monotonic", forbidden)
    monkeypatch.setattr("time.perf_counter", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    reports = [replay_capture(path) for _ in range(3)]
    assert reports[0] == reports[1] == reports[2]
    assert reports[0]["matched"] and reports[0]["actions"] == 1
    assert reports[0]["cycle_results"][0]["final_status"] == "ESCALATED"
    assert not reports[0]["cycle_results"][1]["triggered"]
    assert all(p.read_bytes() == original for p, original in originals.items())


def test_changed_plan_is_a_replay_mismatch_before_execution(tmp_path):
    path = make_capture(tmp_path)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    next(record for record in records if record["event"] == "plan")["payload"]["plan"]["reason"] = "changed"
    # Action-request validation must remain structurally consistent to reach rule comparison.
    next(record for record in records if record["event"] == "action_requested")["payload"]["plan"]["reason"] = "changed"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    with pytest.raises(CaptureError, match="plan payload differs"):
        replay_capture(path)


def test_collector_exception_is_diagnostic_capture_not_fabricated_replay(tmp_path):
    from harness.capture import read_capture
    from harness.capture_validation import validate_capture
    from harness.replay import ReplayMismatch

    path = tmp_path / "exception.jsonl"
    runtime = PatronRuntime(container_name="target", capture_path=path,
        collector=Mock(collect=Mock(side_effect=RuntimeError("collector crashed"))),
        registry=IncidentRegistry(tmp_path / "state.json"),
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"))
    assert runtime.process_once()["error"] == "collector crashed"
    runtime.finish_capture()
    validate_capture(read_capture(path))
    with pytest.raises(ReplayMismatch, match="missing collector observation"):
        replay_capture(path)


def test_operator_acknowledgment_and_rearm_replay_through_control_inbox(tmp_path):
    from uuid import uuid4
    from harness.control import ControlRequest, IncidentControl

    path = tmp_path / "capture.jsonl"
    runtime = PatronRuntime(container_name="target", capture_path=path,
        collector=Mock(collect=Mock(return_value=ContainerSnapshot("target", True, False, "exited", {}, oom_killed=True))),
        registry=IncidentRegistry(tmp_path / "state.json"), audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        executor=Mock(execute=Mock(return_value={"action": "escalate", "success": True})))
    original = runtime.process_once()["incident"]
    for operation in ("acknowledge", "rearm"):
        request = ControlRequest(str(uuid4()), original["incident_id"], runtime.registry.revision,
            operation, "recorded operator action", "tester", runtime.clock.utc_now())
        IncidentControl(runtime.registry, runtime.audit_logger).submit(request)
        result = runtime.process_once()
    assert result["incident"]["predecessor_id"] == original["incident_id"]
    runtime.finish_capture()
    reports = [replay_capture(path) for _ in range(3)]
    assert reports[0] == reports[1] == reports[2]
    assert reports[0]["actions"] == 2
    assert reports[0]["cycle_results"][-1]["final_status"] == "ESCALATED"


def test_three_failed_restarts_escalate_without_a_fourth_action(tmp_path, monkeypatch):
    stopped = ContainerSnapshot("target", True, False, "exited", {}, container_id="generation")
    monkeypatch.setattr("harness.verifier.DockerCollector", Mock(return_value=Mock(collect=Mock(return_value=stopped))))
    path = tmp_path / "retry.jsonl"
    runtime = PatronRuntime(container_name="target", capture_path=path,
        collector=Mock(collect=Mock(return_value=stopped)),
        registry=IncidentRegistry(tmp_path / "state.json"), audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        executor=Mock(execute=Mock(return_value={"action": "restart_container", "success": False})))
    for _ in range(4):
        runtime.process_once()
    runtime.finish_capture()
    report = replay_capture(path)
    assert report["actions"] == 3
    assert [row["attempts"] for row in report["cycle_results"]] == [1, 2, 3, None]
    assert report["cycle_results"][2]["final_status"] == "ESCALATED"
    assert not report["cycle_results"][3]["triggered"]


def test_restart_continuity_replays_initial_open_incident(tmp_path, monkeypatch):
    stopped = ContainerSnapshot("target", True, False, "exited", {}, container_id="generation")
    monkeypatch.setattr("harness.verifier.DockerCollector", Mock(return_value=Mock(collect=Mock(return_value=stopped))))
    paths = []
    for run in range(2):
        path = tmp_path / f"run-{run}.jsonl"
        runtime = PatronRuntime(container_name="target", capture_path=path,
            collector=Mock(collect=Mock(return_value=stopped)),
            registry=IncidentRegistry(tmp_path / "state.json"), audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
            executor=Mock(execute=Mock(return_value={"action": "restart_container", "success": False})))
        result = runtime.process_once()
        assert result["incident"]["attempts"] == run + 1
        runtime.finish_capture()
        paths.append(path)
    for path in paths:
        reports = [replay_capture(path) for _ in range(3)]
        assert reports[0] == reports[1] == reports[2]


def test_collection_error_replays_without_becoming_healthy(tmp_path):
    path = tmp_path / "missing.jsonl"
    runtime = PatronRuntime(container_name="target", capture_path=path,
        collector=Mock(collect=Mock(return_value=ContainerSnapshot("target", False, False, "inspect_failed", {}))),
        registry=IncidentRegistry(tmp_path / "state.json"), audit_logger=AuditLogger(tmp_path / "audit.jsonl"))
    runtime.process_once()
    runtime.finish_capture()
    report = replay_capture(path)
    assert report["actions"] == 0
    assert report["cycle_results"][0]["error"] == "inspect_failed"


@pytest.mark.parametrize("kind,fields", [
    ("STOPPED", {"running": False, "status": "exited"}),
    ("UNHEALTHY", {"health": "unhealthy", "has_healthcheck": True}),
    ("RESTART_LOOP", {"restart_count": 3, "status": "restarting"}),
    ("OOM_KILLED", {"oom_killed": True, "running": False, "status": "exited"}),
    ("HIGH_CPU", {"cpu_percent": 80}),
    ("DISK_FULL", {"disk_usage_percent": 90}),
    ("BAD_CONFIG", {"error_patterns": ["bad_config"], "running": False, "status": "exited"}),
    ("DEPENDENCY_DOWN", {"dependency_status": "down", "health": "unhealthy"}),
])
def test_each_incident_type_replays_with_expected_action_and_final_state(tmp_path, monkeypatch, kind, fields):
    from dataclasses import replace
    clock = FixtureClock()
    healthy = ContainerSnapshot("target", True, True, "running", {}, health="healthy", container_id="generation")
    snapshot = replace(healthy, **fields)
    monkeypatch.setattr("harness.verifier.DockerCollector", Mock(return_value=Mock(collect=Mock(return_value=healthy))))
    decision = "restart_container" if kind in {"STOPPED", "UNHEALTHY"} else "escalate"
    path = tmp_path / "capture.jsonl"
    runtime = PatronRuntime(container_name="target", capture_path=path,
        collector=Mock(collect=Mock(return_value=snapshot)),
        registry=IncidentRegistry(tmp_path / "state.json", clock=clock), audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        executor=Mock(execute=Mock(return_value={"action": decision, "success": True})))
    for offset in ([0, 5, 10] if kind == "HIGH_CPU" else [0]):
        clock.offset = offset
        runtime.collector.collect.return_value = replace(snapshot, observed_monotonic=offset)
        runtime.process_once()
    runtime.finish_capture()
    reports = [replay_capture(path) for _ in range(3)]
    assert reports[0] == reports[1] == reports[2]
    assert reports[0]["actions"] == 1
    final = reports[0]["cycle_results"][-1]
    assert final["incident_type"] == "CONTAINER_" + kind
    assert final["final_status"] == ("RESOLVED" if decision == "restart_container" else "ESCALATED")


def test_cooldown_boundary_replays_without_counting_downtime_as_samples(tmp_path, monkeypatch):
    clock = FixtureClock()
    stopped = ContainerSnapshot("target", True, False, "exited", {}, container_id="generation")
    healthy = ContainerSnapshot("target", True, True, "running", {}, container_id="generation")
    monkeypatch.setattr("harness.verifier.DockerCollector", Mock(return_value=Mock(collect=Mock(return_value=healthy))))
    path = tmp_path / "cooldown.jsonl"
    runtime = PatronRuntime(container_name="target", capture_path=path,
        collector=Mock(collect=Mock(return_value=stopped)),
        registry=IncidentRegistry(tmp_path / "state.json", clock=clock), audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        executor=Mock(execute=Mock(return_value={"action": "restart_container", "success": True})))
    for clock.offset in (0, 59, 60):
        runtime.process_once()
    runtime.finish_capture()
    report = replay_capture(path)
    assert report["actions"] == 2
    assert [row["triggered"] for row in report["cycle_results"]] == [True, False, True]
