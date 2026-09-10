from __future__ import annotations

import argparse
import sys

from .base import ScenarioContext
from .docker_utils import DockerClient, DockerError
from .registry import default_registry, scenario_support_line
from .result import PASSED
from .runner import cleanup_all_simulation_resources, run_scenario


def positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scenarios")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="list registered scenarios")

    run_parser = subparsers.add_parser("run", help="run one scenario")
    run_parser.add_argument("scenario")
    run_parser.add_argument("--target")
    run_parser.add_argument("--timeout", type=positive_int, default=60)
    run_parser.add_argument("--keep-resources", action="store_true")
    run_parser.add_argument("--verbose", action="store_true")
    run_parser.add_argument("--trace", action="store_true")
    run_parser.add_argument("--start-patron", action="store_true", help="launch Patron subprocess (default)")
    run_parser.add_argument("--external-patron", action="store_true", help="wait for a user-managed Patron process")
    run_parser.add_argument("--patron-interval", type=positive_int, default=1)
    run_parser.add_argument("--reset-simulation-state", action="store_true")

    run_all_parser = subparsers.add_parser("run-all", help="run all scenarios")
    run_all_parser.add_argument("--timeout", type=positive_int, default=60)
    run_all_parser.add_argument("--verbose", action="store_true")
    run_all_parser.add_argument("--trace", action="store_true")
    run_all_parser.add_argument("--start-patron", action="store_true", help="launch Patron subprocess (default)")
    run_all_parser.add_argument("--external-patron", action="store_true", help="wait for user-managed Patron processes")
    run_all_parser.add_argument("--patron-interval", type=positive_int, default=1)
    run_all_parser.add_argument("--stop-on-failure", action="store_true")
    run_all_parser.add_argument("--keep-resources", action="store_true")
    run_all_parser.add_argument("--reset-simulation-state", action="store_true")

    cleanup_parser = subparsers.add_parser("cleanup", help="remove Patron simulation resources")
    cleanup_parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "external_patron", False) and getattr(args, "start_patron", False):
        parser.error("--start-patron and --external-patron are mutually exclusive")
    if getattr(args, "reset_simulation_state", False):
        print("Managed runs always use fresh state; external Patron state is never modified.")
    registry = default_registry()

    if args.command == "list":
        for scenario in registry.all():
            print(scenario_support_line(scenario))
        return 0

    if args.command == "cleanup":
        context = ScenarioContext(
            scenario_name="cleanup",
            target_container="",
            verbose=args.verbose,
            docker=DockerClient(),
        )
        try:
            removed = cleanup_all_simulation_resources(context)
        except DockerError as exc:
            print(f"cleanup failed: {exc}", file=sys.stderr)
            return 1
        print(f"Removed {len(removed)} Patron simulation container(s).")
        return 0

    if args.command == "run":
        try:
            scenario = registry.get(args.scenario)
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        target = args.target or scenario.default_target
        context = ScenarioContext(
            scenario_name=scenario.name,
            target_container=target,
            timeout_seconds=args.timeout,
            keep_resources=args.keep_resources,
            verbose=args.verbose,
            trace=args.trace,
            start_patron=not args.external_patron,
            patron_interval=args.patron_interval,
            reset_simulation_state=args.reset_simulation_state,
        )
        result = run_scenario(scenario, context)
        print(result.to_json())
        return 0 if result.status == PASSED else 1

    if args.command == "run-all":
        exit_code = 0
        results = []
        for scenario in registry.all():
            context = ScenarioContext(
                scenario_name=scenario.name,
                target_container=scenario.default_target,
                timeout_seconds=args.timeout,
                keep_resources=args.keep_resources,
                verbose=args.verbose,
                trace=args.trace,
                start_patron=not args.external_patron,
                patron_interval=args.patron_interval,
                reset_simulation_state=args.reset_simulation_state,
            )
            result = run_scenario(scenario, context)
            results.append(result)
            print(result.to_json())
            if result.status != PASSED:
                exit_code = 1
                if args.stop_on_failure:
                    break
        print("Scenario       Target                    Result")
        print("------------------------------------------------")
        for result in results:
            print(f"{result.scenario_name:<14} {result.target:<25} {result.status}")
        return exit_code

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
