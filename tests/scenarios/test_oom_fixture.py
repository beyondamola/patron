from unittest.mock import Mock

from scenarios.docker_utils import DockerClient


def test_oom_fixture_retains_supervisor_and_resource_bounds(monkeypatch):
    client = DockerClient()
    monkeypatch.setattr(client, "_remove_existing_simulation_or_fail", Mock())
    monkeypatch.setattr(client, "run", Mock())
    labels = {"patron.simulation": "true", "patron.scenario_id": "fixture"}
    client.create_oom_container("test-target", labels)
    argv = client.run.call_args.args[0]
    for key, value in (("--memory", "32m"), ("--memory-swap", "32m"),
                       ("--cpus", "1"), ("--pids-limit", "32")):
        assert argv[argv.index(key) + 1] == value
    assert "patron.simulation=true" in argv
    assert "patron.scenario_id=fixture" in argv
    script = argv[-1]
    assert "exec awk" not in script
    assert "awk 'BEGIN" in script and "code=$?; sleep 5; exit" in script
    assert "/tmp/inject-oom" in script
