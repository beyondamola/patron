"""Generate sanitized synthetic captures from the hand-labeled detector corpus."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from uuid import NAMESPACE_URL, uuid5

from harness.audit import AuditLogger
from harness.capture import read_capture
from harness.capture_validation import validate_capture
from harness.collector import ContainerSnapshot
from harness.incident import IncidentRegistry
from harness.replay import replay_capture
from harness.runtime import PatronRuntime


class FixtureClock:
    offset = 0.0

    def utc_now(self):
        return (datetime(2026, 9, 11, tzinfo=timezone.utc) + timedelta(seconds=self.offset)).isoformat()

    def monotonic(self):
        return self.offset

    def sleep(self, seconds):
        self.offset += seconds


def portable(value):
    if isinstance(value, dict):
        return {key: (f"/fixture/{key}.json" if key in {"state_path", "audit_path"} else portable(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [portable(item) for item in value]
    return value


def generate(destination: Path, corpus: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("fixture destination must be empty; never overwrite existing evidence")
    manifest = {"schema_version": 1, "origin": "Synthetic captures generated through PatronRuntime from hand-labeled detector cases; no Docker calls", "fixtures": []}
    cases = json.loads(corpus.read_text())["cases"]
    healthy = ContainerSnapshot("fixture", True, True, "running", {}, health="healthy", container_id="original")
    with patch("harness.verifier.DockerCollector", return_value=Mock(collect=Mock(return_value=healthy))):
        for case in cases:
            with TemporaryDirectory(prefix="patron-fixture-") as directory:
                root = Path(directory)
                clock = FixtureClock()
                counter = 0
                segment = 0
                runtime = None
                expected = []

                def new_id():
                    nonlocal counter
                    counter += 1
                    return str(uuid5(NAMESPACE_URL, f"patron/{case['name']}/{counter}"))

                def finish():
                    runtime.finish_capture()
                    rows = read_capture(path)
                    for record in rows:
                        record["run_id"] = str(uuid5(NAMESPACE_URL, path.name))
                    rows = portable(rows)
                    path.write_text("".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows))
                    validate_capture(rows)
                    report = replay_capture(path)
                    assert [row["incident_type"] for row in report["cycle_results"]] == expected
                    manifest["fixtures"].append({"path": path.name, "source_case": case["name"],
                                                  "expected_incident_types": list(expected)})

                for sample in case["samples"]:
                    if runtime is None or sample.get("restart_runtime"):
                        if runtime is not None:
                            finish()
                            segment += 1
                            expected = []
                        path = destination / f"{case['name']}-{segment}.jsonl"
                        runtime = PatronRuntime(container_name="fixture", capture_path=path,
                            registry=IncidentRegistry(root / "state.json", clock=clock, id_factory=new_id),
                            audit_logger=AuditLogger(root / "audit.jsonl"), collector=Mock(),
                            executor=Mock(execute=lambda plan, context: {"action": plan["decision"], "success": True}))
                    clock.offset = max(clock.offset, sample["time"])
                    values = {"name": "fixture", "exists": True, "running": True, "status": "running",
                              "raw": {}, "container_id": "original", "observed_monotonic": sample["time"],
                              **sample.get("state", {})}
                    if sample.get("invalid_cpu") == "nan":
                        values["cpu_percent"] = float("nan")
                    runtime.collector.collect.return_value = ContainerSnapshot(**values)
                    result = runtime.process_once()
                    actual = (result.get("incident") or {}).get("incident_type")
                    if actual != sample["expected"]:
                        raise ValueError(f"fixture {case['name']} expected {sample['expected']}, got {actual}")
                    expected.append(sample["expected"])
                finish()
        generate_lifecycle(destination, manifest)
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def generate_lifecycle(destination, manifest):
    from harness.control import ControlRequest, IncidentControl
    cases = {
        "retry": [(0, "stopped", None), (5, "stopped", None), (10, "stopped", None), (15, "stopped", None)],
        "cooldown": [(0, "stopped", None), (59, "stopped", None), (60, "stopped", None)],
        "rearm": [(0, "oom", None), (5, "oom", "acknowledge"), (10, "oom", "rearm"), (15, "oom", None)],
        "collection-error": [(0, "healthy", None), (5, "missing", None), (10, "healthy", None)],
        "restart-continuity": [(0, "stopped", None), (5, "stopped", "restart")],
    }
    expected = {
        "retry": ["OPEN", "OPEN", "ESCALATED", None],
        "cooldown": ["RESOLVED", None, "RESOLVED"],
        "rearm": ["ESCALATED", None, "ESCALATED", None],
        "collection-error": [None, None, None],
        "restart-continuity": ["OPEN", "OPEN"],
    }
    for name, steps in cases.items():
        with TemporaryDirectory(prefix="patron-lifecycle-") as directory:
            root = Path(directory)
            clock = FixtureClock()
            counter = 0
            segment = 0
            runtime = None
            expected_types = []
            expected_statuses = []

            def new_id():
                nonlocal counter
                counter += 1
                return str(uuid5(NAMESPACE_URL, f"patron/{name}/{counter}"))

            def finish():
                runtime.finish_capture()
                rows = portable(read_capture(path))
                for row in rows:
                    row["run_id"] = str(uuid5(NAMESPACE_URL, path.name))
                path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
                report = replay_capture(path)
                assert [row["final_status"] for row in report["cycle_results"]] == expected_statuses
                manifest["fixtures"].append({"path": path.name, "source_case": name,
                    "expected_incident_types": list(expected_types), "expected_final_statuses": list(expected_statuses)})

            for index, (offset, kind, operation) in enumerate(steps):
                if runtime is None or operation == "restart":
                    if runtime is not None:
                        finish()
                        segment += 1
                        expected_types, expected_statuses = [], []
                    path = destination / f"lifecycle-{name}-{segment}.jsonl"
                    runtime = PatronRuntime(container_name="fixture", capture_path=path,
                        registry=IncidentRegistry(root / "state.json", clock=clock, id_factory=new_id),
                        audit_logger=AuditLogger(root / "audit.jsonl"), collector=Mock(),
                        executor=Mock(execute=lambda plan, context: {"action": plan["decision"],
                            "success": name not in {"retry", "restart-continuity"}}))
                clock.offset = offset
                if operation in {"acknowledge", "rearm"}:
                    incident = runtime.registry.incidents["fixture"]
                    request = ControlRequest(str(uuid5(NAMESPACE_URL, f"{name}/{operation}")),
                        incident.incident_id, runtime.registry.revision, operation, "fixture operator review",
                        "fixture-operator", clock.utc_now())
                    IncidentControl(runtime.registry, runtime.audit_logger).submit(request)
                runtime.collector.collect.return_value = ContainerSnapshot("fixture", kind != "missing",
                    kind == "healthy", "running" if kind == "healthy" else "inspect_failed" if kind == "missing" else "exited",
                    {}, oom_killed=kind == "oom", container_id="original", observed_monotonic=offset)
                result = runtime.process_once()
                status = (result.get("incident") or {}).get("status")
                assert status == expected[name][index]
                expected_statuses.append(expected[name][index])
                expected_types.append(None if status is None else "CONTAINER_OOM_KILLED" if kind == "oom" else "CONTAINER_STOPPED")
            finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=Path("tests/fixtures/detectors.json"))
    args = parser.parse_args()
    generate(args.output, args.corpus)


if __name__ == "__main__":
    main()
