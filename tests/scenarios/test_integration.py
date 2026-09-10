import os

import pytest
from uuid import uuid4
from pathlib import Path

from scenarios.docker_utils import docker_available
from scenarios.registry import default_registry
from scenarios.base import ScenarioContext
from scenarios.result import ScenarioResultWriter
from scenarios.runner import run_scenario


pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.environ.get("PATRON_RUN_DOCKER_INTEGRATION") != "1" or not docker_available(),
    reason="set PATRON_RUN_DOCKER_INTEGRATION=1 and provide Docker to run integration scenarios",
)
@pytest.mark.parametrize("name", default_registry().names())
def test_real_scenario(name, tmp_path) -> None:
    scenario = default_registry().get(name)
    context = ScenarioContext(name, f"patron-test-{name.replace('_', '-')}-{uuid4().hex[:8]}", timeout_seconds=40)
    result = run_scenario(scenario, context, ScenarioResultWriter(tmp_path / "results.jsonl"))
    assert result.status == "PASSED", result.to_json()
    assert result.classification_correct and result.policy_correct and result.final_status_correct
    assert not context.docker.inspect(context.target_container).exists
    output = Path("logs/scenarios") / context.scenario_id / "patron.log"
    assert "shutdown complete" in output.read_text()
