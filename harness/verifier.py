from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from typing import Any, Callable

from .collector import ContainerSnapshot, DockerCollector

InspectFn = Callable[[str], ContainerSnapshot]


@dataclass(frozen=True)
class VerificationResult:
    checked: bool
    running: bool
    exit_status: int | None
    health: str
    passed: bool
    restart_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_container_running(container_name: str, inspect_fn: InspectFn | None = None) -> bool:
    """Deterministically verify whether a container is running."""

    return verify_container(container_name, inspect_fn=inspect_fn).passed


def verify_container(
    container_name: str,
    inspect_fn: InspectFn | None = None,
) -> VerificationResult:
    """Verify running state, exit status, and health without planner input."""

    if inspect_fn is None:
        inspect_fn = lambda name: DockerCollector(name).collect()
    snapshot = inspect_fn(container_name)
    health = snapshot.health or "none"
    health_ok = health in {"healthy", "none"}
    exit_ok = snapshot.exit_code in {0, None}
    passed = snapshot.exists and snapshot.running and exit_ok and health_ok
    return VerificationResult(
        checked=True,
        running=snapshot.exists and snapshot.running,
        exit_status=snapshot.exit_code,
        health=health,
        passed=passed,
        restart_count=snapshot.restart_count,
    )


def verify_incident(
    container_name: str,
    incident_type: str,
    decision: str,
    inspect_fn: InspectFn | None = None,
    incident_status: str | None = None,
) -> VerificationResult:
    if decision == "escalate":
        return VerificationResult(
            checked=True,
            running=False,
            exit_status=None,
            health="not_applicable",
            passed=incident_status == "ESCALATED",
            restart_count=0,
        )

    live = inspect_fn is None
    if inspect_fn is None:
        inspect_fn = lambda name: DockerCollector(name).collect()
    snapshot = inspect_fn(container_name)
    deadline = time.monotonic() + 8
    while live and incident_type == "CONTAINER_UNHEALTHY" and snapshot.running and snapshot.health != "healthy" and time.monotonic() < deadline:
        time.sleep(0.5)
        snapshot = inspect_fn(container_name)
    health = snapshot.health or "none"

    if incident_type == "CONTAINER_STOPPED":
        passed = snapshot.exists and snapshot.running
    elif incident_type == "CONTAINER_UNHEALTHY":
        passed = snapshot.exists and snapshot.running and health == "healthy"
    else:
        exit_ok = snapshot.exit_code in {0, None}
        health_ok = health in {"healthy", "none"}
        passed = snapshot.exists and snapshot.running and exit_ok and health_ok

    return VerificationResult(
        checked=True,
        running=snapshot.exists and snapshot.running,
        exit_status=snapshot.exit_code,
        health=health,
        passed=passed,
        restart_count=snapshot.restart_count,
    )
