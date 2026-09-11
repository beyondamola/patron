from __future__ import annotations

import json
import shlex
from pathlib import Path

from .base import InjectionResult, ObservationResult, Scenario, ScenarioContext
from .docker_utils import DockerError, normalized_state_packet
from .implementations.utils import seconds_between
from .patron_process import ManagedPatron
from .audit_reader import find_incident_after
from .result import (
    CLEANUP_FAILED,
    FAILED,
    INJECTION_FAILED,
    PASSED,
    SETUP_FAILED,
    TIMED_OUT,
    ScenarioResult,
    ScenarioResultWriter,
)


def run_scenario(
    scenario: Scenario,
    context: ScenarioContext,
    writer: ScenarioResultWriter | None = None,
) -> ScenarioResult:
    writer = writer or ScenarioResultWriter()
    injection = InjectionResult(False, False, None, None)
    observation = ObservationResult(False, False, None, None, None)
    status = FAILED
    error = None
    policy_correct = False
    patron: ManagedPatron | None = None

    try:
        context.detector_config.validate_interval(context.patron_interval)
        context.narrate(f"Creating isolated resources for scenario: {scenario.name}")
        scenario.create_environment(context)
        context.narrate("Confirming healthy baseline")
        scenario.confirm_baseline(context)
        pre_state = context.docker.inspect(context.target_container)
        print_debug_state(context, "pre-state", pre_state)

        if context.start_patron:
            context.narrate(f"Starting Patron for target {context.target_container}")
            patron = ManagedPatron(
                target=context.target_container,
                scenario_id=context.scenario_id,
                interval=context.patron_interval,
                trace=context.trace,
                config=context.detector_config,
            )
            patron.start()
            if not patron.wait_ready():
                raise RuntimeError(f"Patron runtime did not become ready; see {patron.log_path}")
            context.narrate(f"Patron runtime ready; output={patron.log_path}")
        else:
            config_path = Path("logs/scenarios") / context.scenario_id / "detectors.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(context.detector_config.to_dict(), sort_keys=True), encoding="utf-8")
            command = (
                "python -m harness watch "
                f"--target {shlex.quote(context.target_container)} "
                f"--interval {context.patron_interval} --verbose --trace "
                f"--config {shlex.quote(str(config_path.resolve()))}"
            )
            print(f"External Patron mode. Start this command now: {command}", flush=True)

        context.narrate(
            f"scenario_id={context.scenario_id} scenario={context.scenario_name} "
            f"target={context.target_container}"
        )
        expected = getattr(scenario, "expected_failure", lambda: "scenario-specific failure")()
        context.narrate(f"expected failure: {expected}")
        injection = scenario.inject(context)
        post_state = context.docker.inspect(context.target_container)
        print_debug_state(context, "post-state", post_state)
        context.narrate(f"expected failure confirmed={injection.observed}")
        if not injection.injected or not scenario.confirm_injection(context, injection):
            status = INJECTION_FAILED
            error = injection.error or "failure injection was not confirmed"
        else:
            context.narrate("Waiting for Patron response")
            observation = scenario.observe_outcome(context, injection)
            print_debug_state(context, "final-state", context.docker.inspect(context.target_container))
            record = find_incident_after(
                observation.expected_incident_type or "", context.target_container,
                injection.injected_at or context.started_at,
            )
            expected_action = "escalate" if observation.expected_final_status == "ESCALATED" else "restart_container"
            policy_correct = bool(record and not record.get("dry_run")
                and (record.get("policy_result") or {}).get("allowed") is True
                and (record.get("planner_output") or {}).get("decision") == expected_action
                and (record.get("action_executed") or {}).get("action") == expected_action
                and (record.get("action_executed") or {}).get("success") is True)
            if observation.recovered and policy_correct and observation.expected_final_status == observation.observed_final_status:
                status = PASSED
            elif observation.error and "timed out" in observation.error:
                status = TIMED_OUT
                error = observation.error
            else:
                status = FAILED
                error = observation.error
    except DockerError as exc:
        status = SETUP_FAILED if not injection.injected else INJECTION_FAILED
        error = str(exc)
    except Exception as exc:
        status = SETUP_FAILED if not injection.injected else FAILED
        error = str(exc)
    finally:
        if patron is not None:
            context.narrate("Stopping Patron")
            try:
                patron.stop()
            except Exception as exc:
                status = CLEANUP_FAILED
                shutdown_error = f"Patron shutdown failed: {exc}"
                error = f"{error}; {shutdown_error}" if error else shutdown_error
        cleanup_error = None
        if not context.keep_resources:
            context.narrate("Cleaning up")
            try:
                scenario.cleanup(context)
            except Exception as exc:
                cleanup_error = str(exc)
                if status == PASSED:
                    status = CLEANUP_FAILED

    if cleanup_error:
        error = f"{error}; cleanup failed: {cleanup_error}" if error else f"cleanup failed: {cleanup_error}"

    result = build_result(context, status, injection, observation, error)
    result.policy_correct = policy_correct
    writer.write(result)
    context.narrate(f"Result: {result.status}")
    return result


def print_debug_state(context: ScenarioContext, label: str, state) -> None:
    packet = normalized_state_packet(state)
    evidence = Path("logs/scenarios") / context.scenario_id
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / f"{label}.json").write_text(json.dumps(packet, indent=2, sort_keys=True))
    if not (context.verbose or context.trace):
        return
    context.narrate(
        f"target={packet['name']} id={packet['id']} labels={json.dumps(packet['labels'], sort_keys=True)}"
    )
    print(f"[Scenario] {label}: {json.dumps(packet, indent=2, sort_keys=True)}")


def build_result(
    context: ScenarioContext,
    status: str,
    injection: InjectionResult,
    observation: ObservationResult,
    error: str | None,
) -> ScenarioResult:
    return ScenarioResult(
        scenario_id=context.scenario_id,
        scenario_name=context.scenario_name,
        target=context.target_container,
        detector_config=context.detector_config.to_dict(),
        detector_config_fingerprint=context.detector_config.fingerprint,
        status=status,
        failure_injected=injection.injected,
        failure_observed=injection.observed,
        recovery_observed=observation.recovered,
        injected_at=injection.injected_at,
        detected_at=observation.detected_at,
        recovered_at=observation.recovered_at,
        detection_latency_seconds=seconds_between(injection.injected_at, observation.detected_at),
        recovery_latency_seconds=seconds_between(injection.injected_at, observation.recovered_at),
        final_container_state=observation.final_state,
        error=error,
        patron_incident_id=observation.patron_incident_id,
        expected_incident_type=observation.expected_incident_type,
        observed_incident_type=observation.observed_incident_type,
        expected_final_status=observation.expected_final_status,
        observed_final_status=observation.observed_final_status,
        classification_correct=(
            observation.expected_incident_type == observation.observed_incident_type
            if observation.expected_incident_type and observation.observed_incident_type
            else None
        ),
        policy_correct=(
            observation.expected_final_status == observation.observed_final_status
            if observation.expected_final_status and observation.observed_final_status
            else None
        ),
        final_status_correct=(
            observation.expected_final_status == observation.observed_final_status
            if observation.expected_final_status and observation.observed_final_status
            else None
        ),
    )


def cleanup_all_simulation_resources(context: ScenarioContext) -> list[str]:
    context.narrate("Cleaning up Patron simulation containers")
    containers = context.docker.cleanup_simulation_containers()
    networks = context.docker.remove_simulation_networks()
    return containers + networks
