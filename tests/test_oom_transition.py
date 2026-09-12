from dataclasses import replace
from unittest.mock import Mock

from harness.audit import AuditLogger
from harness.collector import ContainerSnapshot
from harness.incident import IncidentRegistry
from harness.runtime import PatronRuntime
from harness.triggers import default_trigger_registry


def test_delayed_oom_metadata_never_causes_generic_restart(tmp_path):
    ambiguous = ContainerSnapshot("target", True, False, "exited", {}, exit_code=137, container_id="same")
    collector = Mock(collect=Mock(side_effect=[ambiguous, replace(ambiguous, oom_killed=True)]))
    executor = Mock(execute=Mock(return_value={"action": "escalate", "success": True}))
    runtime = PatronRuntime(container_name="target", collector=collector, executor=executor,
        registry=IncidentRegistry(tmp_path / "state.json"), audit_logger=AuditLogger(tmp_path / "audit.jsonl"))
    first = runtime.process_once()
    assert not first["triggered"] and not first["healthy"]
    executor.execute.assert_not_called()
    second = runtime.process_once()
    assert second["incident"]["incident_type"] == "CONTAINER_OOM_KILLED"
    assert second["incident"]["status"] == "ESCALATED"
    assert executor.execute.call_count == 1
    assert executor.execute.call_args.args[0]["decision"] == "escalate"


def test_sigkill_is_not_inferred_to_be_oom_and_explains_rejection():
    snapshot = ContainerSnapshot("target", True, False, "exited", {}, exit_code=137)
    packet, traces = default_trigger_registry().evaluate_with_trace(snapshot)
    assert packet is None
    stopped = next(row for row in traces if row["incident_type"] == "CONTAINER_STOPPED")
    assert not stopped["result"] and "cause unconfirmed" in stopped["reason"]
    assert not next(row for row in traces if row["incident_type"] == "CONTAINER_OOM_KILLED")["result"]
    assert default_trigger_registry().evaluate(replace(snapshot, exit_code=0))["incident_type"] == "CONTAINER_STOPPED"
