from unittest.mock import Mock
from dataclasses import replace

import pytest

from harness.audit import AuditLogger
from harness.collector import ContainerSnapshot
from harness.comparison import compare_capture
from harness.config import DetectorConfig
from harness.incident import IncidentRegistry
from harness.runtime import PatronRuntime
from harness.shadow import FakeCandidate


@pytest.fixture
def capture(tmp_path, monkeypatch):
    healthy = ContainerSnapshot("target", True, True, "running", {})
    monkeypatch.setattr("harness.verifier.DockerCollector", Mock(return_value=Mock(collect=Mock(return_value=healthy))))
    path = tmp_path / "capture.jsonl"
    runtime = PatronRuntime(container_name="target", capture_path=path,
        collector=Mock(collect=Mock(return_value=replace(healthy, running=False, status="exited"))),
        registry=IncidentRegistry(tmp_path / "state.json"), audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        executor=Mock(execute=Mock(return_value={"action": "restart_container", "success": True})))
    runtime.process_once()
    runtime.collector.collect.return_value = healthy
    runtime.process_once()
    runtime.finish_capture()
    return path


def test_mirror_comparison_deterministic_and_no_live_dependencies(capture, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("comparison invoked a live dependency")
    for name in ("DockerCollector", "DockerExecutor", "PatronRuntime"):
        monkeypatch.setattr("harness.runtime." + name, forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("time.sleep", forbidden)
    reports = [compare_capture(capture, DetectorConfig(), DetectorConfig()) for _ in range(3)]
    assert reports[0] == reports[1] == reports[2]
    assert reports[0]["regressions"] == 0 and not reports[0]["execution_enabled"]


def test_changed_action_cannot_inherit_recorded_recovery(capture):
    report = compare_capture(capture, DetectorConfig(), DetectorConfig(), FakeCandidate("escalate"))
    assert report["regressions"] == 1
    first = report["observations"][0]
    assert first["recorded_final_status"] == "RESOLVED"
    assert first["candidate_final_status"] is None
    assert all(row["outcome_evidence"] == "counterfactual_unknown" for row in report["observations"])


def test_malformed_candidate_is_counted_and_denied(capture):
    report = compare_capture(capture, DetectorConfig(), DetectorConfig(), FakeCandidate("malformed"))
    assert report["malformed_plans"] == report["policy_denials"] == 1


def test_changed_probe_cannot_reuse_old_measurements(capture):
    with pytest.raises(ValueError, match="probe evidence"):
        compare_capture(capture, DetectorConfig(), DetectorConfig(disk_path="/different"))
