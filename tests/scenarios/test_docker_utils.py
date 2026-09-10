from scenarios.docker_utils import (
    SCENARIO_ID_LABEL,
    MANAGED_LABEL,
    SIMULATION_LABEL,
    ContainerState,
    DockerClient,
    DockerError,
    is_simulation_resource,
    wait_until,
)


def test_wait_until_times_out_without_busy_loop() -> None:
    assert not wait_until(lambda: False, timeout_seconds=0, poll_interval_seconds=0.001)


def test_simulation_label_filter_requires_patron_label() -> None:
    state = ContainerState(
        name="x",
        exists=True,
        running=True,
        status="running",
        health=None,
        exit_code=0,
        restart_count=0,
        labels={SIMULATION_LABEL: "true", SCENARIO_ID_LABEL: "abc"},
    )

    assert is_simulation_resource(state)
    assert is_simulation_resource(state, "abc")
    assert not is_simulation_resource(state, "other")


def test_simulation_labels_include_managed_ownership() -> None:
    from scenarios.docker_utils import simulation_labels

    labels = simulation_labels("stopped", "scenario-1")

    assert labels[SIMULATION_LABEL] == "true"
    assert labels[MANAGED_LABEL] == "true"
    assert labels[SCENARIO_ID_LABEL] == "scenario-1"


def test_cleanup_only_removes_listed_simulation_containers() -> None:
    class FakeDocker(DockerClient):
        def __init__(self) -> None:
            self.updated = []
            self.removed = []

        def list_simulation_containers(self):
            return ["container-1", "container-2"]

        def update_restart_policy(self, name, policy):
            self.updated.append((name, policy))

        def remove_container(self, name):
            self.removed.append(name)

    docker = FakeDocker()

    removed = docker.cleanup_simulation_containers()

    assert removed == ["container-1", "container-2"]
    assert docker.updated == [("container-1", "no"), ("container-2", "no")]
    assert docker.removed == ["container-1", "container-2"]


def test_dedicated_container_creation_refuses_unrelated_existing_target() -> None:
    class FakeDocker(DockerClient):
        def inspect(self, name):
            return ContainerState(name, True, True, "running", None, 0, 0, {})

    docker = FakeDocker()

    try:
        docker.create_healthcheck_container("existing", {SIMULATION_LABEL: "true"})
    except DockerError as exc:
        assert "non-simulation container" in str(exc)
    else:
        raise AssertionError("expected DockerError")
