from harness.audit import AuditLogger
from harness.collector import ContainerSnapshot
from harness.incident import ESCALATED, IncidentRegistry
from harness.runtime import PatronRuntime
from harness.verifier import VerificationResult


class StoppedCollector:
    def collect(self) -> ContainerSnapshot:
        return ContainerSnapshot(
            "mvp-nginx",
            exists=True,
            running=False,
            status="exited",
            raw={},
            exit_code=1,
        )


class RestartLoopCollector:
    def collect(self) -> ContainerSnapshot:
        return ContainerSnapshot(
            "patron-restart-loop",
            exists=True,
            running=False,
            status="restarting",
            raw={"Restarting": True},
            exit_code=1,
            restart_count=3,
        )


class FailedExecutor:
    def execute(self, plan, context):
        return {
            "action": plan["decision"],
            "target": context["resource"],
            "returncode": 1,
            "stdout": "",
            "stderr": "restart failed",
            "success": False,
        }


def test_runtime_escalates_after_three_failed_attempts(tmp_path) -> None:
    registry = IncidentRegistry(state_path=tmp_path / "state.json", cooldown_seconds=60)
    runtime = PatronRuntime(
        collector=StoppedCollector(),
        registry=registry,
        audit_logger=AuditLogger(tmp_path / "incidents.jsonl"),
    )
    runtime.verifier = lambda *_: VerificationResult(
        checked=True,
        running=False,
        exit_status=1,
        health="not_configured",
        passed=False,
    )
    runtime.executor = FailedExecutor()

    for _ in range(3):
        result = runtime.process_once()

    assert result["incident"]["status"] == ESCALATED
    assert result["incident"]["attempts"] == 3


def test_runtime_escalates_restart_loop_immediately(tmp_path) -> None:
    registry = IncidentRegistry(state_path=tmp_path / "state.json", cooldown_seconds=60)
    runtime = PatronRuntime(
        collector=RestartLoopCollector(),
        registry=registry,
        audit_logger=AuditLogger(tmp_path / "incidents.jsonl"),
    )

    result = runtime.process_once()

    assert result["incident"]["status"] == ESCALATED
    assert result["audit"]["planner_output"]["decision"] == "escalate"
    assert result["audit"]["metrics"]["incident_type"] == "CONTAINER_RESTART_LOOP"
    assert result["audit"]["metrics"]["verification_latency_seconds"] is not None

    next_result = runtime.process_once()

    assert not next_result["triggered"]
    assert next_result["cooldown"]
