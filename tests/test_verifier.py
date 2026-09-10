from harness.collector import ContainerSnapshot
from harness.verifier import is_container_running, verify_container, verify_incident


def test_verifier_returns_true_when_container_running() -> None:
    def inspect(_: str) -> ContainerSnapshot:
        return ContainerSnapshot("mvp-nginx", exists=True, running=True, status="running", raw={})

    assert is_container_running("mvp-nginx", inspect_fn=inspect)


def test_verifier_returns_false_when_container_exited() -> None:
    def inspect(_: str) -> ContainerSnapshot:
        return ContainerSnapshot("mvp-nginx", exists=True, running=False, status="exited", raw={})

    assert not is_container_running("mvp-nginx", inspect_fn=inspect)


def test_verifier_checks_unhealthy_container() -> None:
    def inspect(_: str) -> ContainerSnapshot:
        return ContainerSnapshot(
            "mvp-nginx",
            exists=True,
            running=True,
            status="running",
            raw={},
            exit_code=0,
            health="unhealthy",
        )

    result = verify_container("mvp-nginx", inspect_fn=inspect)

    assert result.running
    assert result.health == "unhealthy"
    assert not result.passed


def test_stopped_incident_verifier_only_requires_running() -> None:
    def inspect(_: str) -> ContainerSnapshot:
        return ContainerSnapshot(
            "mvp-nginx",
            exists=True,
            running=True,
            status="running",
            raw={},
            exit_code=0,
            health="unhealthy",
        )

    result = verify_incident(
        "mvp-nginx",
        "CONTAINER_STOPPED",
        "restart_container",
        inspect_fn=inspect,
    )

    assert result.passed


def test_unhealthy_incident_verifier_requires_healthy_status() -> None:
    def inspect(_: str) -> ContainerSnapshot:
        return ContainerSnapshot(
            "mvp-nginx",
            exists=True,
            running=True,
            status="running",
            raw={},
            exit_code=0,
            health="healthy",
        )

    result = verify_incident(
        "mvp-nginx",
        "CONTAINER_UNHEALTHY",
        "restart_container",
        inspect_fn=inspect,
    )

    assert result.passed


def test_restart_loop_escalation_verifier_passes_internal_escalation() -> None:
    result = verify_incident("mvp-nginx", "CONTAINER_RESTART_LOOP", "escalate", incident_status="ESCALATED")

    assert result.checked
    assert result.passed
    assert result.health == "not_applicable"
