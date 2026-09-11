import json
from unittest.mock import Mock

import pytest

from harness.audit import AuditLogger
from harness.capture import CaptureError
from harness.collector import ContainerSnapshot
from harness.incident import IncidentRegistry
from harness.replay import replay_capture
from harness.runtime import PatronRuntime


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
