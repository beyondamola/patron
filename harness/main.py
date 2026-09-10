from __future__ import annotations

import argparse
import json

from .collector import DockerCollector
from .runtime import PatronRuntime


def positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def run(
    container_name: str = "mvp-nginx",
    dry_run: bool = False,
    verbose: bool = False,
    trace: bool = False,
) -> int:
    result = PatronRuntime(
        container_name=container_name,
        dry_run=dry_run,
        verbose=verbose,
        trace=trace,
    ).process_once()
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

    watch_parser = subparsers.add_parser("watch", help="run the remediation daemon")
    watch_parser.add_argument("--container", "--target", dest="container", default="mvp-nginx")
    watch_parser.add_argument("--interval", type=positive_int, default=10)
    watch_parser.add_argument("--dry-run", action="store_true")
    watch_parser.add_argument("--verbose", action="store_true")
    watch_parser.add_argument("--trace", action="store_true")

    inspect_parser = subparsers.add_parser("inspect-docker", help="print normalized Docker state")
    inspect_parser.add_argument("--target", "--container", dest="container", default="mvp-nginx")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return run(
            container_name=args.container,
            dry_run=args.dry_run,
            verbose=args.verbose,
            trace=args.trace,
        )
    if args.command == "watch":
        return PatronRuntime(
            container_name=args.container,
            dry_run=args.dry_run,
            verbose=args.verbose,
            trace=args.trace,
        ).watch(interval=args.interval)
    if args.command == "inspect-docker":
        snapshot = DockerCollector(args.container).collect()
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
