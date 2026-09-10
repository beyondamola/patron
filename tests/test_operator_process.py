"""Real process qualification; never writes Patron state directly."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from scenarios.base import ScenarioContext
from scenarios.docker_utils import docker_available
from scenarios.registry import default_registry
from scenarios.runner import run_scenario


pytestmark = [pytest.mark.operator_integration, pytest.mark.skipif(
    os.environ.get("PATRON_RUN_DOCKER_INTEGRATION") != "1",
    reason="operator process tests require explicit Docker opt-in")]


def until(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError("Timed out waiting for operator workflow")


def test_real_operator_workflow():
    assert docker_available(), "Docker required for operator qualification"
    scenario = default_registry().get("oom_killed")
    context = ScenarioContext("oom_killed", f"patron-ops-{uuid4().hex[:10]}", keep_resources=True, trace=True)
    root = Path("logs/scenarios") / context.scenario_id
    state = root / "incident_state.json"
    processes = []
    handles = []

    def command(*args):
        return subprocess.run([sys.executable, "-m", "harness", *args],
                              capture_output=True, text=True, timeout=20)

    def operator(action, incident_id=None, *args):
        result = command("incidents", action, *([incident_id] if incident_id else []),
                         "--state-path", str(state), "--json", *args)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    def start_watch(index):
        path = root / f"operator-watch-{index}.log"
        handle = path.open("w")
        handles.append(handle)
        process = subprocess.Popen([sys.executable, "-u", "-m", "harness", "watch",
            "--target", context.target_container, "--state-path", str(state), "--interval", "1", "--verbose"],
            stdout=handle, stderr=subprocess.STDOUT)
        processes.append(process)
        until(lambda: process.poll() is not None or "[Collector]" in path.read_text())
        assert process.poll() is None, path.read_text()
        return process, path

    def stop(process, path):
        process.send_signal(signal.SIGINT)
        assert process.wait(timeout=15) == 0
        assert "shutdown complete" in path.read_text()

    def latest_new(old_id):
        records = operator("list")["incidents"]
        return next((item for item in records if item.get("predecessor_id") == old_id
                     and item["status"] == "ESCALATED"), None)

    try:
        result = run_scenario(scenario, context)
        assert result.status == "PASSED", result.to_json()
        first_id = result.patron_incident_id
        process, path = start_watch(1)
        blocked = command("run", "--target", context.target_container, "--state-path", str(state))
        assert blocked.returncode != 0 and "owned by another" in blocked.stderr
        request_id = str(uuid4())
        applied = operator("acknowledge", first_id, "--reason", "investigating", "--request-id", request_id, "--wait", "10")
        duplicate = operator("acknowledge", first_id, "--reason", "investigating", "--request-id", request_id)
        assert applied == duplicate
        def concurrent_ack(index):
            return command("incidents", "acknowledge", first_id, "--state-path", str(state),
                           "--json", "--reason", f"parallel-{index}", "--wait", "10")
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(concurrent_ack, (1, 2)))
        assert all(response.stdout for response in responses), [(response.returncode, response.stderr) for response in responses]
        outcomes = [json.loads(response.stdout) for response in responses]
        assert any(outcome["status"] == "APPLIED" for outcome in outcomes)
        assert all(outcome["status"] in {"APPLIED", "REJECTED"} for outcome in outcomes)
        for outcome in outcomes:
            saved = operator("show", first_id, "--request-id", outcome["request_id"])["request"]
            assert saved["status"] == outcome["status"]
            if outcome["status"] == "REJECTED":
                operator("acknowledge", first_id, "--reason", outcome["reason"], "--wait", "10")
        assert operator("rearm", first_id, "--reason", "reviewed", "--dry-run")["status"] == "DRY_RUN"
        operator("rearm", first_id, "--reason", "reviewed", "--wait", "10")
        second = until(lambda: latest_new(first_id))
        time.sleep(2)
        assert len([item for item in operator("list")["incidents"] if item.get("predecessor_id") == first_id]) == 1
        stop(process, path)
        operator("acknowledge", second["incident_id"], "--reason", "offline review")
        operator("rearm", second["incident_id"], "--reason", "offline rearm")
        process, path = start_watch(2)
        third = until(lambda: latest_new(second["incident_id"]))
        assert third["container_id"] == second["container_id"]
        stop(process, path)
        assert context.docker.inspect(context.target_container).oom_killed
        records = operator("list")["incidents"]
        assert all(item["status"] == "ESCALATED" and item["attempts"] == 0 for item in records)
    finally:
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for handle in handles:
            handle.close()
        scenario.cleanup(context)
        assert not context.docker.inspect(context.target_container).exists
