import json
from pathlib import Path

import pytest

from harness.capture import read_capture
from harness.main import main
from harness.replay_provenance import lab_provenance


CAPTURE = Path(__file__).parent / "fixtures/replay/cpu-boundary-0.jsonl"


@pytest.fixture
def provenance(tmp_path):
    records = read_capture(CAPTURE)
    incident = next(row["payload"]["incident"] for row in records if row["event"] == "transition")
    result = {"scenario_id": "synthetic-lab-timing", "patron_incident_id": incident["incident_id"],
        "target": incident["resource"], "observed_incident_type": incident["incident_type"],
        "detector_config_fingerprint": records[0]["payload"]["config_fingerprint"],
        "injected_at": records[0]["utc_time"], "failure_injected": True, "failure_observed": True}
    path = tmp_path / "results.jsonl"
    path.write_text(json.dumps(result) + "\n")
    return path, result


def test_known_lab_delay_is_separate_and_repeatable(provenance):
    path, _ = provenance
    reports = [lab_provenance(CAPTURE, path) for _ in range(3)]
    assert reports[0] == reports[1] == reports[2]
    assert reports[0]["incidents"][0]["detection_latency_seconds"] == 10
    assert reports[0]["candidate_detection_latency_seconds"] is None


@pytest.mark.parametrize("key,value", [("target", "other"), ("detector_config_fingerprint", "wrong"),
    ("observed_incident_type", "CONTAINER_STOPPED"), ("failure_observed", False),
    ("injected_at", "2030-01-01T00:00:00+00:00"), ("injected_at", "2026-09-11T00:00:00"),
    ("patron_incident_id", {}), ("patron_incident_id", "unrelated")])
def test_mismatched_provenance_rejected(provenance, key, value):
    path, result = provenance
    result[key] = value
    path.write_text(json.dumps(result) + "\n")
    with pytest.raises(ValueError):
        lab_provenance(CAPTURE, path)


def test_unknown_onset_remains_unknown(provenance):
    path, result = provenance
    result["injected_at"] = None
    path.write_text(json.dumps(result) + "\n")
    assert lab_provenance(CAPTURE, path)["incidents"][0]["detection_latency_seconds"] is None


def test_setup_injection_can_precede_runtime_capture(provenance):
    path, result = provenance
    result["injected_at"] = "2026-09-10T23:59:59+00:00"
    path.write_text(json.dumps(result) + "\n")
    incident = lab_provenance(CAPTURE, path)["incidents"][0]
    assert incident["onset_precedes_capture"] is True
    assert incident["detection_latency_seconds"] == 11


def test_duplicate_and_incomplete_results_rejected(provenance):
    path, result = provenance
    path.write_text((json.dumps(result) + "\n") * 2)
    with pytest.raises(ValueError, match="duplicate"):
        lab_provenance(CAPTURE, path)
    path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="incomplete"):
        lab_provenance(CAPTURE, path)


def test_cli_keeps_runtime_latency_unknown_and_cannot_overwrite_provenance(provenance, tmp_path):
    path, _ = provenance
    output = tmp_path / "report.json"
    args = ["replay", "run", str(CAPTURE), "--scenario-results", str(path), "--output"]
    assert main(args + [str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["lab_provenance"]["incidents"][0]["detection_latency_seconds"] == 10
    assert report["recorded_metrics"][0]["detection_latency_seconds"] is None
    original = path.read_bytes()
    assert main(args + [str(path)]) == 1
    assert path.read_bytes() == original


def test_comparison_provenance_never_supplies_candidate_outcome(provenance, tmp_path):
    path, _ = provenance
    config = tmp_path / "config.json"
    config.write_text("{}")
    output = tmp_path / "comparison.json"
    assert main(["replay", "compare", str(CAPTURE), "--baseline-config", str(config),
        "--candidate-config", str(config), "--fake-candidate", "malformed",
        "--scenario-results", str(path), "--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["lab_provenance"]["incidents"][0]["detection_latency_seconds"] == 10
    assert report["lab_provenance"]["candidate_detection_latency_seconds"] is None
    assert all(row["candidate_final_status"] is None for row in report["observations"])
    assert report["observations"][-1]["outcome_evidence"] == "counterfactual_unknown"
