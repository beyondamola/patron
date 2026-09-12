import os
import json

import pytest
from uuid import uuid4
from pathlib import Path

from scenarios.docker_utils import docker_available
from scenarios.registry import default_registry
from scenarios.base import ScenarioContext
from scenarios.result import ScenarioResultWriter
from scenarios.runner import run_scenario
from harness.replay import replay_capture
from harness.replay_provenance import lab_provenance


pytestmark = pytest.mark.integration


@pytest.fixture
def require_docker():
    enabled = os.environ.get("PATRON_RUN_DOCKER_INTEGRATION") == "1"
    strict = os.environ.get("PATRON_CI_STRICT") == "1"
    if not enabled or not docker_available():
        message = "set PATRON_RUN_DOCKER_INTEGRATION=1 and provide Docker"
        if strict:
            pytest.fail(message)
        pytest.skip(message)


@pytest.mark.parametrize("name", default_registry().names())
def test_real_scenario(name, tmp_path, require_docker) -> None:
    scenario = default_registry().get(name)
    context = ScenarioContext(name, f"patron-test-{name.replace('_', '-')}-{uuid4().hex[:8]}",
                              timeout_seconds=120, verbose=True, trace=True, capture=True)
    result_path = Path("logs/scenarios") / context.scenario_id / "result.jsonl"
    result = run_scenario(scenario, context, ScenarioResultWriter(result_path))
    assert result.status == "PASSED", result.to_json()
    assert result.classification_correct and result.policy_correct and result.final_status_correct
    assert not context.docker.inspect(context.target_container).exists
    for resource_type, listing in (("container", ["ps", "-aq"]),
                                   ("network", ["network", "ls", "-q"]),
                                   ("volume", ["volume", "ls", "-q"])):
        remaining = context.docker.run([
            *listing, "--filter", "label=patron.simulation=true",
            "--filter", f"label=patron.scenario_id={context.scenario_id}",
        ])
        assert not remaining.stdout, f"leaked {resource_type}: {remaining.stdout}"
    output = Path("logs/scenarios") / context.scenario_id / "patron.log"
    assert "shutdown complete" in output.read_text()
    capture = output.with_name("capture.jsonl")
    reports = [replay_capture(capture) for _ in range(3)]
    assert reports[0] == reports[1] == reports[2]
    assert reports[0]["matched"]
    incidents = [cycle for cycle in reports[0]["cycle_results"] if cycle["triggered"]]
    assert incidents and incidents[-1]["incident_type"] == result.expected_incident_type
    assert incidents[-1]["final_status"] == result.expected_final_status
    provenance = lab_provenance(capture, result_path)
    assert provenance["incidents"][0]["incident_id"] == result.patron_incident_id
    assert provenance["incidents"][0]["detection_latency_seconds"] is not None
    reports[0]["lab_provenance"] = provenance
    output.with_name("replay-report.json").write_text(json.dumps(reports[0], indent=2, sort_keys=True))
