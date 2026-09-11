import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from harness.collector import (
    ContainerSnapshot, collect_cpu_percent, collect_dependency_status,
    collect_disk_usage_percent, collect_recent_logs, enrich_snapshot,
    snapshot_from_docker_inspect,
)
from harness.triggers.dependency_down import ContainerDependencyDownTrigger


def command_response(monkeypatch, stdout="", returncode=0):
    run = Mock(return_value=Mock(returncode=returncode, stdout=stdout, stderr=""))
    monkeypatch.setattr("harness.collector.docker_run", run)
    return run


def test_logs_only_use_current_start_and_recent_timestamped_evidence(monkeypatch):
    run = command_response(monkeypatch, "\n".join([
        "2026-09-11T12:00:00Z CONFIG_ERROR old start",
        "2026-09-11T12:00:45.123456789Z current message",
        "CONFIG_ERROR missing timestamp",
        "2026-09-11T12:02:00Z CONFIG_ERROR future",
    ]))
    errors = {}
    logs = collect_recent_logs("immutable-id", started_at="2026-09-11T12:00:30Z",
                               now=datetime(2026, 9, 11, 12, 1, tzinfo=timezone.utc), errors=errors)
    assert logs == ["current message"]
    assert "logs_filtered" in errors
    assert run.call_args.args[0] == ["docker", "logs", "--timestamps", "--since",
                                    "2026-09-11T12:00:30+00:00", "--tail", "20", "immutable-id"]


def test_old_config_evidence_expires_even_without_a_restart(monkeypatch):
    command_response(monkeypatch, "2026-09-11T12:00:00Z CONFIG_ERROR old")
    assert collect_recent_logs("x", started_at="2026-09-11T11:00:00Z",
        now=datetime(2026, 9, 11, 12, 2, tzinfo=timezone.utc)) == []


@pytest.mark.parametrize("start", [None, "invalid", "0001-01-01T00:00:00Z", "2099-01-01T00:00:00Z"])
def test_unknown_start_cannot_provide_current_log_evidence(monkeypatch, start):
    run = command_response(monkeypatch)
    errors = {}
    assert collect_recent_logs("x", started_at=start, errors=errors) == []
    assert errors["logs"]
    run.assert_not_called()


@pytest.mark.parametrize("payload", [[], {}, [{}], [{"State": {}}], [{"State": {"Running": "false"}}], None])
def test_dependency_requires_positive_typed_inspect_evidence(monkeypatch, payload):
    command_response(monkeypatch, json.dumps(payload))
    status = collect_dependency_status("dependency")
    assert status == "unknown"
    snapshot = ContainerSnapshot("app", True, True, "running", {}, dependency_status=status)
    assert not ContainerDependencyDownTrigger().evaluate(snapshot)


def test_dependency_inspect_failure_is_not_down(monkeypatch):
    command_response(monkeypatch, returncode=1)
    assert collect_dependency_status("dependency") == "unknown"


@pytest.mark.parametrize("running,expected", [(True, "running"), (False, "down")])
def test_dependency_inspect_valid_state(monkeypatch, running, expected):
    command_response(monkeypatch, json.dumps([{"State": {"Running": running}}]))
    assert collect_dependency_status("dependency") == expected


@pytest.mark.parametrize("value", ["NaN%", "Infinity%", "-2%", "", "not-a-number"])
def test_invalid_cpu_measurements_remain_unknown(monkeypatch, value):
    command_response(monkeypatch, json.dumps({"CPUPerc": value}))
    assert collect_cpu_percent("x") is None


@pytest.mark.parametrize("output", ["", "header\ninvalid", "header\nx x x x NaN% /tmp", "header\nx x x x 101% /tmp"])
def test_unavailable_disk_metrics_are_not_zero(monkeypatch, output):
    command_response(monkeypatch, output)
    assert collect_disk_usage_percent("x", "/tmp") is None


def test_disk_path_is_one_literal_argument(monkeypatch):
    run = command_response(monkeypatch, "header\nx x x x 90% /tmp")
    path = "/tmp/a path;echo injected"
    assert collect_disk_usage_percent("id", path) == 90
    assert run.call_args.args[0] == ["docker", "exec", "id", "df", "-P", "--", path]
    run.reset_mock()
    assert collect_disk_usage_percent("id", "relative") is None
    run.assert_not_called()


def test_quota_is_exposed_without_changing_cpu_denominator():
    snapshot = snapshot_from_docker_inspect("x", {"State": {"Running": True},
        "HostConfig": {"CpuQuota": 50000, "CpuPeriod": 100000, "NanoCpus": 500000000}})
    assert (snapshot.cpu_quota, snapshot.cpu_period, snapshot.nano_cpus) == (50000, 100000, 500000000)


def test_probe_errors_are_explanations_not_fabricated_measurements(monkeypatch):
    command_response(monkeypatch, returncode=1)
    result = enrich_snapshot("name", ContainerSnapshot("name", True, True, "running", {},
        container_id="id", labels={"patron.dependency": "service"}))
    assert result.cpu_percent is None and result.disk_usage_percent is None
    assert result.dependency_status == "unknown"
    assert set(result.probe_errors) == {"logs", "cpu", "disk", "dependency"}
    assert result.observed_monotonic is not None
