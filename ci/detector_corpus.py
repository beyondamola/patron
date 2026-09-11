"""Evaluate hand-labeled detector fixtures; no executor or live collector is used."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from harness.collector import ContainerSnapshot
from harness.context_manager import build_context
from harness.incident import Incident
from harness.planner import RulePlanner
from harness.policy import validate_plan
from harness.triggers import default_trigger_registry
from harness.triggers.high_cpu import ContainerHighCPUTrigger


def evaluate(corpus: dict) -> dict:
    if corpus.get("schema_version") != 1:
        raise ValueError("unsupported detector corpus schema")
    types = [trigger.incident_type for trigger in default_trigger_registry().triggers]
    counts = {kind: {"positive_samples": 0, "negative_samples": 0,
                     "false_positives": 0, "false_negatives": 0} for kind in types}
    observations = []
    failures = []
    for case in corpus["cases"]:
        now = 0
        registry = None
        for index, sample in enumerate(case["samples"]):
            now = max(now, sample["time"])
            if registry is None or sample.get("restart_runtime"):
                registry = default_trigger_registry()
                for trigger in registry.triggers:
                    if isinstance(trigger, ContainerHighCPUTrigger):
                        trigger.clock = lambda: now
            state = {"name": "fixture", "exists": True, "running": True,
                     "status": "running", "raw": {}, "container_id": "original",
                     "observed_monotonic": sample["time"], **sample.get("state", {})}
            if sample.get("invalid_cpu") == "nan":
                state["cpu_percent"] = float("nan")
            expected = sample["expected"]
            if expected is not None and expected not in types:
                raise ValueError(f"unknown expected classification: {expected}")
            snapshot = ContainerSnapshot(**state)
            packet, traces = registry.evaluate_with_trace(snapshot)
            observed = packet["incident_type"] if packet else None
            action = None
            allowed = None
            if packet:
                incident = Incident("fixture", "fixture", "docker_container", observed,
                                    "OPEN", 0, "2026-09-11T00:00:00Z", "2026-09-11T00:00:00Z")
                context = build_context(snapshot, incident, packet)
                plan = RulePlanner().plan(context)
                action = plan["decision"]
                allowed = validate_plan(plan, context).allowed
            expected_action = (None if expected is None else "restart_container"
                if expected in {"CONTAINER_STOPPED", "CONTAINER_UNHEALTHY"} else "escalate")
            correct = observed == expected and action == expected_action and (allowed is True if expected else allowed is None)
            row = {"case": case["name"], "sample": index, "expected": expected,
                   "observed": observed, "action": action, "policy_allowed": allowed,
                   "correct": correct, "traces": traces}
            observations.append(row)
            if not correct:
                failures.append({key: value for key, value in row.items() if key != "traces"})
            for kind, count in counts.items():
                count["positive_samples" if expected == kind else "negative_samples"] += 1
                count["false_positives"] += int(observed == kind and expected != kind)
                count["false_negatives"] += int(observed != kind and expected == kind)
    return {"schema_version": 1, "scope": "synthetic observation classification, not lifecycle replay or field accuracy",
            "case_count": len(corpus["cases"]), "sample_count": len(observations),
            "per_incident_type": counts, "failures": failures, "observations": observations}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("tests/fixtures/detectors.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/raw/detector-corpus.json"))
    args = parser.parse_args()
    report = evaluate(json.loads(args.corpus.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "observations"}, indent=2))
    return int(bool(report["failures"]))


if __name__ == "__main__":
    raise SystemExit(main())
