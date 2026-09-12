import json
from pathlib import Path

from harness.main import main
from harness.replay import replay_capture


ROOT = Path(__file__).parent / "fixtures" / "replay"


def test_exact_agreement_has_denominators_and_does_not_count_suppression_twice():
    report = replay_capture(ROOT / "lifecycle-retry-0.jsonl")
    stats = report["agreement"]["per_incident_type"]["CONTAINER_STOPPED"]
    assert stats == {"positive_samples": 4, "total_samples": 4,
        "classification_agreements": 4, "terminal_outcomes": 1, "final_state_agreements": 1}
    assert [row["attempts"] for row in report["cycle_results"][:3]] == [1, 2, 3]
    assert report["agreement"]["action_differences"] == 0
    assert all(row["detection_latency_seconds"] is None for row in report["recorded_metrics"])


def test_cli_timing_is_separate_from_deterministic_content(tmp_path, monkeypatch):
    ticks = iter((10.0, 10.5, 20.0, 21.0))
    monkeypatch.setattr("time.perf_counter", lambda: next(ticks))
    reports = []
    for index in range(2):
        output = tmp_path / f"report-{index}.json"
        assert main(["replay", "run", str(ROOT / "stopped-0.jsonl"), "--output", str(output)]) == 0
        reports.append(json.loads(output.read_text()))
    assert reports[0].pop("report_metadata")["computation_seconds"] == 0.5
    assert reports[1].pop("report_metadata")["computation_seconds"] == 1.0
    assert reports[0] == reports[1]


def test_threshold_comparison_cli_reports_regression_and_unknown_outcomes(tmp_path):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text("{}")
    candidate.write_text('{"disk_threshold": 95}')
    output = tmp_path / "comparison.json"
    assert main(["replay", "compare", str(ROOT / "disk-boundary-priority-0.jsonl"),
        "--baseline-config", str(baseline), "--candidate-config", str(candidate),
        "--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["per_incident_type"]["CONTAINER_DISK_FULL"]["missed"] == 1
    assert report["action_differences"] == 1
    assert report["final_state_agreement"]["comparable"] == 0
    assert report["final_state_agreement"]["unknown"] == 1
    assert report["observations"][0]["outcome_evidence"] == "counterfactual_unknown"
    assert report["report_metadata"]["computation_seconds"] >= 0
