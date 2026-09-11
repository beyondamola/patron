from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from harness.audit import AuditLogger
from harness.collector import ContainerSnapshot
from harness.incident import IncidentRegistry
from harness.runtime import PatronRuntime
from harness.verifier import VerificationResult


class RecordedClock:
    def __init__(self):
        self.offset = 0.0

    def utc_now(self):
        return (datetime(2026, 9, 11, tzinfo=timezone.utc) + timedelta(seconds=self.offset)).isoformat()

    def monotonic(self):
        return self.offset

    def sleep(self, seconds):
        self.offset += seconds


def test_registry_ids_timestamps_and_cooldown_use_supplied_clock(tmp_path):
    clock = RecordedClock()
    ids = iter(["first", "second"])
    registry = IncidentRegistry(tmp_path / "state.json", clock=clock, id_factory=lambda: next(ids))
    args = ("target", "docker_container", "CONTAINER_STOPPED", "stopped")
    first, created = registry.get_or_open(*args)
    assert created and first.incident_id == "first" and first.created_at == clock.utc_now()
    clock.sleep(5)
    registry.mark_resolved(first)
    assert first.updated_at == clock.utc_now()
    clock.sleep(59)
    assert registry.get_or_open(*args) == (None, False)
    clock.sleep(1)
    second, created = registry.get_or_open(*args)
    assert created and second.incident_id == "second"
    assert second.created_at == clock.utc_now()


def test_runtime_stage_metrics_and_transitions_use_explicit_dependencies(tmp_path, monkeypatch):
    clock = RecordedClock()
    registry = IncidentRegistry(tmp_path / "state.json", clock=clock, id_factory=lambda: "recorded-id")
    snapshot = ContainerSnapshot("target", True, False, "exited", {}, container_id="generation")

    def collect():
        clock.sleep(1)
        return snapshot

    def plan(context):
        clock.sleep(2)
        return {"decision": "restart_container", "reason": "recorded", "confidence": 1.0}

    def execute(plan, context):
        clock.sleep(3)
        return {"action": "restart_container", "success": True}

    def verify(*args, **kwargs):
        clock.sleep(4)
        return VerificationResult(True, True, 0, "none", True)

    def forbidden(*args, **kwargs):
        raise AssertionError("live clock used")

    monkeypatch.setattr("time.monotonic", forbidden)
    monkeypatch.setattr("time.perf_counter", forbidden)
    monkeypatch.setattr("time.sleep", forbidden)
    runtime = PatronRuntime(collector=Mock(collect=collect), registry=registry,
        planner=Mock(plan=plan), executor=Mock(execute=execute), verifier=verify,
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"))
    result = runtime.process_once()
    assert result["incident"]["incident_id"] == "recorded-id"
    assert result["incident"]["status"] == "RESOLVED"
    assert result["incident"]["updated_at"] == clock.utc_now()
    metrics = result["audit"]["metrics"]
    assert metrics["planning_latency_seconds"] == 2
    assert metrics["execution_latency_seconds"] == 3
    assert metrics["verification_latency_seconds"] == 4
