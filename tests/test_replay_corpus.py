import json
from pathlib import Path

import pytest

from harness.replay import equivalent, replay_capture


ROOT = Path(__file__).parent / "fixtures/replay"
MANIFEST = json.loads((ROOT / "manifest.json").read_text())


@pytest.mark.parametrize("fixture", MANIFEST["fixtures"], ids=lambda item: item["path"])
def test_committed_replay_fixture(fixture, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("live dependency invoked in committed replay corpus")
    for target in ("time.sleep", "time.monotonic", "time.perf_counter", "subprocess.Popen", "socket.socket.connect",
                   "harness.runtime.DockerCollector", "harness.runtime.DockerExecutor"):
        monkeypatch.setattr(target, forbidden)
    reports = [replay_capture(ROOT / fixture["path"]) for _ in range(3)]
    assert reports[0] == reports[1] == reports[2]
    assert [row["incident_type"] for row in reports[0]["cycle_results"]] == fixture["expected_incident_types"]
    if "expected_final_statuses" in fixture:
        assert [row["final_status"] for row in reports[0]["cycle_results"]] == fixture["expected_final_statuses"]


def test_duration_tolerance_does_not_weaken_decision_comparison():
    assert equivalent({"coverage_seconds": 3.296255499999}, {"coverage_seconds": 3.296255500001})
    assert not equivalent({"coverage_seconds": 3.296255}, {"coverage_seconds": 3.296258})
    assert not equivalent({"threshold": 80}, {"threshold": 80.0000001})
    assert not equivalent({"result": True}, {"result": False})
