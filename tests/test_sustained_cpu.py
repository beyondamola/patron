from dataclasses import replace

import pytest

from harness.collector import ContainerSnapshot
from harness.config import DetectorConfig
from harness.triggers.base import TriggerRegistry
from harness.triggers.high_cpu import ContainerHighCPUTrigger
from harness.triggers.oom_killed import ContainerOOMKilledTrigger


class Samples:
    def __init__(self):
        self.now = 0.0
        self.trigger = ContainerHighCPUTrigger(clock=lambda: self.now)

    def sample(self, timestamp, value=80.0, **changes):
        self.now = max(self.now, timestamp)
        return ContainerSnapshot("cpu", True, True, "running", {}, container_id="first",
                                 cpu_percent=value, observed_monotonic=timestamp, **changes)

    def observe(self, timestamp, value=80.0, **changes):
        return self.trigger.trace(self.sample(timestamp, value, **changes))


def test_three_samples_and_ten_seconds_are_both_required():
    s = Samples()
    assert not s.observe(0)["result"]
    assert not s.observe(1)["result"]
    assert not s.observe(2)["result"]
    trace = s.observe(10)
    assert trace["result"] and trace["coverage_seconds"] == 10
    s = Samples()
    assert not s.observe(0)["result"]
    assert not s.observe(10)["result"]
    assert s.observe(20)["result"]


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -1, 79.99, 0])
def test_invalid_or_below_threshold_breaks_unconfirmed_window(value):
    s = Samples()
    s.observe(0)
    s.observe(5)
    assert not s.observe(10, value)["result"]
    assert not s.observe(15)["result"]
    assert not s.observe(20)["result"]
    assert s.observe(25)["result"]


@pytest.mark.parametrize("timestamp", [5, 4, -20])
def test_duplicate_out_of_order_and_stale_observations_reset_window(timestamp):
    s = Samples()
    s.observe(0)
    s.observe(5)
    rejected = s.observe(timestamp)
    assert not rejected["result"] and rejected["sample_count"] == 0
    assert not s.observe(10)["result"]
    assert not s.observe(15)["result"]
    assert s.observe(20)["result"]


def test_gap_resets_sequence_and_trace_does_not_double_count():
    s = Samples()
    first = s.sample(0)
    assert not s.trigger.evaluate(first)
    assert s.trigger.trace(first)["sample_count"] == 1
    s.observe(5)
    trace = s.observe(21)
    assert not trace["result"] and trace["sample_count"] == 1
    assert not s.observe(26)["result"]
    assert s.observe(31)["result"]


def test_generation_and_runtime_restart_rebuild_partial_window():
    s = Samples()
    s.observe(0)
    s.observe(5)
    replacement = replace(s.sample(10), container_id="second")
    assert not s.trigger.evaluate(replacement)
    assert s.trigger.trace(replacement)["sample_count"] == 1
    fresh = ContainerHighCPUTrigger(clock=lambda: s.now)
    assert not fresh.evaluate(replacement)


def test_counter_reset_breaks_sequence():
    s = Samples()
    s.observe(0, restart_count=2)
    s.observe(5, restart_count=2)
    trace = s.observe(10, restart_count=0)
    assert not trace["result"] and trace["reason"] == "restart counter reset"


def test_hysteresis_requires_valid_sustained_recovery():
    s = Samples()
    for stamp in (0, 5, 10):
        trace = s.observe(stamp)
    assert trace["result"]
    assert s.observe(15, 70)["result"]
    assert s.observe(20, 60)["result"]
    missing = s.observe(25, None)
    assert not missing["result"] and missing["alarm_latched"]
    assert s.observe(30, 60)["result"]
    assert not s.observe(35, 60)["alarm_latched"]


def test_registry_keeps_window_current_even_when_higher_priority_wins():
    s = Samples()
    registry = TriggerRegistry([ContainerOOMKilledTrigger(), s.trigger])
    for stamp in (0, 5, 10):
        snapshot = replace(s.sample(stamp), oom_killed=True)
        packet, traces = registry.evaluate_with_trace(snapshot)
        assert packet["incident_type"] == "CONTAINER_OOM_KILLED"
        assert traces[0]["selected"] and not traces[1]["selected"]
    assert traces[1]["result"]
    assert registry.evaluate(s.sample(15))["incident_type"] == "CONTAINER_HIGH_CPU"


@pytest.mark.parametrize("kwargs", [
    {"cpu_threshold": float("nan")}, {"cpu_max_gap_seconds": -1},
    {"cpu_min_samples": True}, {"cpu_min_samples": 1}, {"disk_threshold": 101},
    {"cpu_recovery_threshold": 80}, {"disk_path": "relative"}, {"dependency": ""},
    {"restart_loop_threshold": 0}, {"cpu_window_seconds": float("inf")},
])
def test_invalid_detector_settings_fail_closed(kwargs):
    with pytest.raises(ValueError):
        DetectorConfig(**kwargs)


def test_configuration_round_trip_and_fingerprint(tmp_path):
    import json

    config = DetectorConfig()
    path = tmp_path / "detectors.json"
    path.write_text(json.dumps(config.to_dict()))
    assert DetectorConfig.load(path) == config
    assert len(config.fingerprint) == 64
    assert replace(config, cpu_threshold=90).fingerprint != config.fingerprint
    path.write_text('{"unknown": 1}')
    with pytest.raises(ValueError, match="invalid detector"):
        DetectorConfig.load(path)


@pytest.mark.parametrize("interval", [0, -1, 15, 30, float("nan"), True])
def test_poll_interval_cannot_make_detection_impossible(interval):
    with pytest.raises(ValueError, match="poll interval"):
        DetectorConfig().validate_interval(interval)


def test_cli_validates_config_before_collecting(tmp_path, capsys):
    from harness.main import main

    path = tmp_path / "invalid.json"
    path.write_text('{"cpu_min_samples": 0}')
    assert main(["inspect-docker", "--config", str(path)]) == 1
    assert "cpu_min_samples" in capsys.readouterr().err


def test_collection_failure_breaks_window_without_resolving_incidents(tmp_path):
    from unittest.mock import Mock
    from harness.audit import AuditLogger
    from harness.incident import IncidentRegistry
    from harness.runtime import PatronRuntime

    s = Samples()
    collector = Mock()
    runtime = PatronRuntime(collector=collector,
        registry=IncidentRegistry(tmp_path / "state.json"),
        audit_logger=AuditLogger(tmp_path / "audit.jsonl"),
        triggers=TriggerRegistry([s.trigger]))
    for stamp in (0, 5):
        collector.collect.return_value = s.sample(stamp)
        assert not runtime.process_once()["triggered"]
    collector.collect.return_value = replace(s.sample(6), exists=False, status="inspect_failed")
    assert runtime.process_once()["error"] == "inspect_failed"
    collector.collect.return_value = s.sample(10)
    assert not runtime.process_once()["triggered"]
    assert s.trigger.trace(collector.collect.return_value)["sample_count"] == 1
