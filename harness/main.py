from __future__ import annotations

import argparse
import json
import sys
import getpass
import math

from .collector import DockerCollector
from .config import DetectorConfig
from .capture import CaptureError
from .runtime import PatronRuntime
from .incident import IncidentRegistry
from .storage import StateConflict
from .control import IncidentControl, execute_request


def positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def bounded_wait(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0 or result > 300:
        raise argparse.ArgumentTypeError("wait must be between 0 and 300 seconds")
    return result


def run(
    container_name: str = "mvp-nginx",
    dry_run: bool = False,
    verbose: bool = False,
    trace: bool = False,
    state_path: str | None = None,
    config: DetectorConfig | None = None,
    capture_path: str | None = None,
) -> int:
    runtime = PatronRuntime(
        container_name=container_name,
        dry_run=dry_run,
        verbose=verbose,
        trace=trace,
        registry=IncidentRegistry(state_path),
        config=config,
        capture_path=capture_path,
    )
    complete = False
    try:
        result = runtime.process_once()
        complete = True
    finally:
        runtime.finish_capture(complete=complete)
    if not result.get("triggered"):
        if result.get("error"):
            print(f"Collection failed: {result['error']}")
            return 1
        if result.get("cooldown"):
            print(f"No incident: {container_name} is in cooldown.")
        elif result.get("healthy"):
            print(f"No incident: {container_name} is running.")
        else:
            print(
                "No incident: no registered trigger matched "
                f"{container_name} status {result.get('snapshot_status')}."
            )
        return 0
    incident = result["incident"]
    if dry_run:
        print(f"Dry run planned remediation for {container_name}; incident logged.")
        return 0
    if incident["status"] == "RESOLVED":
        print(f"Remediated {container_name}; incident logged.")
        return 0
    if incident["status"] == "ESCALATED":
        print(f"Escalated {container_name} after {incident['attempts']} attempts; incident logged.")
        return 1

    print(f"Remediation attempt recorded for {container_name}; incident logged.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m harness")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run the remediation harness")
    run_parser.add_argument("--container", "--target", dest="container", default="mvp-nginx")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--verbose", action="store_true")
    run_parser.add_argument("--trace", action="store_true")
    run_parser.add_argument("--state-path")

    watch_parser = subparsers.add_parser("watch", help="run the remediation daemon")
    watch_parser.add_argument("--container", "--target", dest="container", default="mvp-nginx")
    watch_parser.add_argument("--interval", type=positive_int, default=10)
    watch_parser.add_argument("--dry-run", action="store_true")
    watch_parser.add_argument("--verbose", action="store_true")
    watch_parser.add_argument("--trace", action="store_true")
    watch_parser.add_argument("--state-path")

    inspect_parser = subparsers.add_parser("inspect-docker", help="print normalized Docker state")
    inspect_parser.add_argument("--target", "--container", dest="container", default="mvp-nginx")
    for command in (run_parser, watch_parser, inspect_parser):
        command.add_argument("--config", help="validated detector settings JSON file")
    for command in (run_parser, watch_parser):
        command.add_argument("--capture", help="new normalized observation JSONL capture path")
    incident_parser = subparsers.add_parser("incidents", help="inspect and control incident suppression")
    commands = incident_parser.add_subparsers(dest="incident_command", required=True)
    for name in ("list", "show", "acknowledge", "rearm"):
        command = commands.add_parser(name)
        command.add_argument("--state-path")
        command.add_argument("--json", action="store_true")
        if name != "list":
            command.add_argument("incident_id")
        if name == "show":
            command.add_argument("--request-id", help="also show a queued/completed request")
        if name in {"acknowledge", "rearm"}:
            command.add_argument("--reason", required=True)
            command.add_argument("--actor", default=getpass.getuser())
            command.add_argument("--request-id")
            command.add_argument("--dry-run", action="store_true")
            command.add_argument("--wait", type=bounded_wait, default=5.0)
    replay_parser = subparsers.add_parser("replay", help="validate recorded runtime evidence")
    replay_commands = replay_parser.add_subparsers(dest="replay_command", required=True)
    validate_parser = replay_commands.add_parser("validate", help="validate capture structure and causal references")
    validate_parser.add_argument("capture_path")
    replay_run = replay_commands.add_parser("run", help="reproduce recorded decisions with execution disabled")
    replay_run.add_argument("capture_path")
    replay_run.add_argument("--output", required=True)
    compare = replay_commands.add_parser("compare", help="compare offline detector/planner recommendations")
    compare.add_argument("capture_path")
    compare.add_argument("--baseline-config", required=True)
    compare.add_argument("--candidate-config", required=True)
    compare.add_argument("--fake-candidate", choices=("mirror", "escalate", "malformed"), default="mirror")
    compare.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except (CaptureError, StateConflict, ValueError, OSError) as exc:
        print(f"Patron error: {exc}", file=sys.stderr)
        return 1


def _main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "replay":
        from time import perf_counter
        if args.replay_command == "compare":
            from pathlib import Path
            from .comparison import compare_capture
            from .shadow import FakeCandidate
            output = Path(args.output)
            sources = (args.capture_path, args.baseline_config, args.candidate_config)
            if output.resolve() in {Path(source).resolve() for source in sources}:
                raise ValueError("comparison output must not overwrite an input")
            started = perf_counter()
            report = compare_capture(args.capture_path, DetectorConfig.load(args.baseline_config),
                DetectorConfig.load(args.candidate_config), FakeCandidate(args.fake_candidate))
            report["report_metadata"] = {"computation_seconds": perf_counter() - started,
                "scope": "capture validation and comparison; excludes output serialization",
                "semantic": False}
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
            print(json.dumps({key: report[key] for key in
                ("regressions", "malformed_plans", "action_differences", "policy_denials")}))
            return int(bool(report["regressions"]))
        if args.replay_command == "run":
            from pathlib import Path
            from .replay import replay_capture
            output = Path(args.output)
            if output.resolve() == Path(args.capture_path).resolve():
                raise ValueError("replay output must not overwrite input capture")
            started = perf_counter()
            report = replay_capture(args.capture_path)
            report["report_metadata"] = {"computation_seconds": perf_counter() - started,
                "scope": "capture validation and exact replay; excludes output serialization",
                "semantic": False}
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
            print(json.dumps({"matched": report["matched"], "cycles": report["cycles"], "actions": report["actions"]}))
            return 0
        from .capture import read_capture
        from .capture_validation import validate_capture
        summary = validate_capture(read_capture(args.capture_path))
        print(json.dumps({"valid": True, **summary}, sort_keys=True))
        return 0
    if args.command == "incidents":
        registry = IncidentRegistry(args.state_path)
        control = IncidentControl(registry)
        if args.incident_command == "list":
            payload = {"incidents": list(control.incidents().values())}
        elif args.incident_command == "show":
            incident = control.incidents().get(args.incident_id)
            if not incident:
                raise ValueError("Incident not found in the selected state/audit history")
            payload = {"incident": incident}
            if args.request_id:
                payload["request"] = control.request_result(args.request_id) or {"request_id": args.request_id, "status": "PENDING_OR_UNKNOWN"}
        else:
            payload = execute_request(registry, args.incident_command, args.incident_id,
                args.reason, args.actor, args.request_id, args.dry_run, args.wait)
        payload["state_path"] = str(registry.state_path)
        print(json.dumps(payload, indent=None if args.json else 2, sort_keys=True))
        return 0 if payload.get("status") not in {"REJECTED", "PENDING", "PENDING_AUDIT"} else 1
    config = DetectorConfig.load(args.config) if args.config else DetectorConfig()
    if args.command == "run":
        return run(
            container_name=args.container,
            dry_run=args.dry_run,
            verbose=args.verbose,
            trace=args.trace,
            state_path=args.state_path,
            config=config,
            capture_path=args.capture,
        )
    if args.command == "watch":
        return PatronRuntime(
            container_name=args.container,
            dry_run=args.dry_run,
            verbose=args.verbose,
            trace=args.trace,
            registry=IncidentRegistry(args.state_path),
            config=config,
            capture_path=args.capture,
        ).watch(interval=args.interval)
    if args.command == "inspect-docker":
        snapshot = DockerCollector(args.container, config=config).collect()
        payload = {
            "name": snapshot.name,
            "id": snapshot.container_id,
            "exists": snapshot.exists,
            "status": snapshot.status,
            "running": snapshot.running,
            "exit_code": snapshot.exit_code,
            "restart_count": snapshot.restart_count,
            "health_status": snapshot.health or "none",
            "has_healthcheck": snapshot.has_healthcheck,
            "restart_policy": snapshot.restart_policy,
            "labels": snapshot.labels or {},
        }
        payload.update({key: value for key, value in snapshot.to_dict().items() if key not in {"raw", "health", "container_id"}})
        payload["error"] = snapshot.raw.get("stderr")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if snapshot.exists else 1
    return 2
