from harness.collector import detect_error_patterns, snapshot_from_docker_inspect


def test_collector_normalizes_missing_health_to_none() -> None:
    snapshot = snapshot_from_docker_inspect(
        "mvp-nginx",
        {
            "Id": "abc",
            "RestartCount": 0,
            "State": {"Running": True, "Status": "running", "ExitCode": 0},
            "Config": {"Labels": {}},
            "HostConfig": {"RestartPolicy": {"Name": "no"}},
        },
    )

    assert snapshot.health is None
    assert not snapshot.has_healthcheck


def test_collector_extracts_health_status_when_present() -> None:
    snapshot = snapshot_from_docker_inspect(
        "mvp-nginx",
        {
            "Id": "abc",
            "RestartCount": 0,
            "State": {
                "Running": True,
                "Status": "running",
                "ExitCode": 0,
                "Health": {"Status": "unhealthy"},
            },
            "Config": {"Labels": {}, "Healthcheck": {"Test": ["CMD", "true"]}},
            "HostConfig": {"RestartPolicy": {"Name": "no"}},
        },
    )

    assert snapshot.health == "unhealthy"
    assert snapshot.has_healthcheck


def test_collector_extracts_restart_count_policy_and_labels() -> None:
    snapshot = snapshot_from_docker_inspect(
        "mvp-nginx",
        {
            "Id": "abc",
            "RestartCount": 4,
            "State": {"Running": False, "Status": "restarting", "ExitCode": 1},
            "Config": {"Labels": {"patron.simulation": "true"}},
            "HostConfig": {"RestartPolicy": {"Name": "always"}},
        },
    )

    assert snapshot.restart_count == 4
    assert snapshot.restart_policy == "always"
    assert snapshot.labels == {"patron.simulation": "true"}


def test_collector_extracts_oom_killed() -> None:
    snapshot = snapshot_from_docker_inspect(
        "mvp-nginx",
        {
            "Id": "abc",
            "RestartCount": 0,
            "State": {"Running": False, "Status": "exited", "ExitCode": 137, "OOMKilled": True},
            "Config": {"Labels": {}},
            "HostConfig": {"RestartPolicy": {"Name": "no"}, "Memory": 33554432},
        },
    )

    assert snapshot.oom_killed
    assert snapshot.memory_limit_bytes == 33554432


def test_error_pattern_detection() -> None:
    patterns = detect_error_patterns([
        "CONFIG_ERROR invalid config",
        "DEPENDENCY_DOWN dependency unavailable",
        "no space left on device",
    ])

    assert patterns == ["bad_config", "dependency_down", "disk_full"]
def test_terminal_inspection_refreshes_delayed_oom_evidence(monkeypatch):
    import json
    from unittest.mock import Mock
    from harness.collector import DockerCollector
    payload = {"Id": "container-id", "State": {"Running": False, "Status": "exited", "OOMKilled": False}}
    final = {**payload, "State": {**payload["State"], "OOMKilled": True}}
    run = Mock(side_effect=[Mock(returncode=0, stdout=json.dumps([payload])),
                            Mock(returncode=0, stdout=json.dumps([final]))])
    monkeypatch.setattr("harness.collector.docker_run", run)
    monkeypatch.setattr("harness.collector.enrich_snapshot", lambda name, snapshot, **kwargs: snapshot)
    assert DockerCollector("target").collect().oom_killed
    assert run.call_args.args[0] == ["docker", "inspect", "container-id"]
