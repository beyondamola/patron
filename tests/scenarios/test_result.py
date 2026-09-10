import json

from scenarios.result import PASSED, ScenarioResult


def test_scenario_result_serializes_to_json() -> None:
    result = ScenarioResult(
        scenario_id="scenario-1",
        scenario_name="stopped",
        target="mvp-nginx",
        status=PASSED,
        failure_injected=True,
        failure_observed=True,
        recovery_observed=True,
        injected_at="2026-06-07T00:00:00+00:00",
        detected_at="2026-06-07T00:00:02+00:00",
        recovered_at="2026-06-07T00:00:04+00:00",
        detection_latency_seconds=2.0,
        recovery_latency_seconds=4.0,
        final_container_state="running",
        error=None,
        patron_incident_id="incident-1",
        expected_incident_type="CONTAINER_STOPPED",
        observed_incident_type="CONTAINER_STOPPED",
        expected_final_status="RESOLVED",
        observed_final_status="RESOLVED",
        classification_correct=True,
        policy_correct=True,
        final_status_correct=True,
    )

    payload = json.loads(result.to_json())

    assert payload["status"] == "PASSED"
    assert payload["scenario_name"] == "stopped"
    assert payload["classification_correct"]
