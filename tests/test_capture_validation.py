from copy import deepcopy
from unittest.mock import Mock

import pytest

from harness.audit import AuditLogger
from harness.capture import read_capture
from harness.capture_validation import validate_capture
from harness.collector import ContainerSnapshot
from harness.incident import IncidentRegistry
from harness.main import main
from harness.runtime import PatronRuntime


@pytest.fixture
def capture(tmp_path):
    path = tmp_path / "capture.jsonl"
    runtime = PatronRuntime(container_name="target",
        collector=Mock(collect=Mock(return_value=ContainerSnapshot("target", True, False, "exited", {}, oom_killed=True))),
        registry=IncidentRegistry(tmp_path / "state.json"),
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"), capture_path=path,
        executor=Mock(execute=Mock(return_value={"action": "escalate", "success": True})))
    runtime.process_once()
    runtime.finish_capture()
    return path, read_capture(path)


def test_real_runtime_capture_validates_and_cli_is_read_only(capture):
    path, rows = capture
    before = path.read_bytes()
    assert validate_capture(rows) == {"cycles": 1, "actions": 1, "verifier_observations": 0}
    assert main(["replay", "validate", str(path)]) == 0
    assert path.read_bytes() == before


@pytest.mark.parametrize("history", [None, {}, [None], [{"incident": {}}],
    [{"event": "operator_control", "event_id": "a", "result": {"request_id": "b"}}],
    [{"incident": {"incident_id": "a", "resource": "x", "status": "RESOLVED"}, "state_path": "/live"}]])
def test_invalid_control_history_is_rejected(capture, history):
    _, original = capture
    rows = deepcopy(original)
    rows[0]["payload"]["control_history"] = history
    with pytest.raises(ValueError):
        validate_capture(rows)


@pytest.mark.parametrize("event,key,value,message", [
    ("observation", "observation_id", 999, "parent reference"),
    ("plan", "observation_id", 999, "observation reference"),
    ("transition", "incident_id", "other", "incident reference"),
    ("verification", "incident_id", "other", "incident reference"),
])
def test_event_references(capture, event, key, value, message):
    _, original = capture
    rows = deepcopy(original)
    record = next(row for row in rows if row["event"] == event)
    record[key] = value
    with pytest.raises(ValueError, match=message):
        validate_capture(rows)


@pytest.mark.parametrize("kind", ["missing_state", "boolean_revision", "typed_running", "wrong_target", "action_without_policy", "missing_outcome", "missing_control_state"])
def test_corrupt_payload_or_causal_chain_fails_closed(capture, kind):
    _, original = capture
    rows = deepcopy(original)
    if kind == "missing_state":
        rows[0]["payload"]["initial_state"].pop("incidents")
    elif kind == "boolean_revision":
        rows[0]["payload"]["initial_state"]["revision"] = True
    elif kind in {"typed_running", "wrong_target"}:
        snapshot = next(row for row in rows if row["event"] == "observation")["payload"]["snapshot"]
        snapshot["running" if kind == "typed_running" else "name"] = "false" if kind == "typed_running" else "other"
    elif kind == "action_without_policy":
        next(row for row in rows if row["event"] == "policy")["payload"]["policy"]["allowed"] = False
    elif kind == "missing_outcome":
        rows = [row for row in rows if row["event"] != "verification"]
    else:
        rows[-1]["payload"]["state"].pop("control_results")
    with pytest.raises(ValueError):
        validate_capture(rows)
