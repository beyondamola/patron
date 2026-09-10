from __future__ import annotations

from .utils import wait_for_audit_detection
from ..base import InjectionResult, ObservationResult, Scenario, ScenarioContext, utc_now
from ..docker_utils import is_simulation_resource, wait_until


class RestartLoopScenario(Scenario):
    name = "restart_loop"
    description = "Run a container that repeatedly exits under a Docker restart policy."
    default_target = "patron-sim-restart-loop"
    incident_type = "CONTAINER_RESTART_LOOP"
    restart_threshold = 3

    def setup(self, context: ScenarioContext) -> None:
        context.narrate(f"Preparing scenario: {self.name}")
        context.docker.create_restart_loop_container(context.target_container, context.labels)

    def validate_preconditions(self, context: ScenarioContext) -> None:
        state = context.docker.inspect(context.target_container)
        if not state.exists:
            raise RuntimeError(f"{context.target_container} was not created")

    def inject(self, context: ScenarioContext) -> InjectionResult:
        context.narrate("Injecting failure: waiting for restart loop threshold")
        injected_at = context.started_at
        observed = wait_until(
            lambda: self.failure_confirmed(context),
            timeout_seconds=min(20, context.timeout_seconds),
            poll_interval_seconds=context.poll_interval_seconds,
        )
        if observed:
            context.narrate("Failure confirmed: restart count crossed threshold")
        return InjectionResult(True, observed, injected_at, utc_now())

    def observe(self, context: ScenarioContext, injection: InjectionResult) -> ObservationResult:
        context.narrate("Waiting for Patron classification and escalation")
        detected_at = None
        escalated_at = None
        patron_incident = None

        def escalated() -> bool:
            nonlocal detected_at, escalated_at, patron_incident
            incident = wait_for_audit_detection(
                self.incident_type,
                context.target_container,
                injection.injected_at or context.started_at,
                return_record=True,
            )
            if incident:
                patron_incident = incident or patron_incident
                detected_at = detected_at or (incident.get("timestamps") or {}).get("updated_at")
                if incident.get("final_status") == "ESCALATED":
                    escalated_at = escalated_at or (incident.get("timestamps") or {}).get("updated_at") or utc_now()
            return escalated_at is not None

        ok = wait_until(escalated, context.timeout_seconds, context.poll_interval_seconds)
        state = context.docker.inspect(context.target_container)
        if ok:
            context.narrate("Expected outcome observed: incident escalated")
        return ObservationResult(
            detected=detected_at is not None,
            recovered=ok,
            detected_at=detected_at,
            recovered_at=escalated_at,
            final_state=f"{state.status}:restart_count={state.restart_count}",
            error=None if ok else "timed out waiting for restart-loop escalation",
            patron_incident_id=patron_incident.get("incident_id") if patron_incident else None,
            expected_incident_type=self.incident_type,
            observed_incident_type=patron_incident.get("incident_type") if patron_incident else None,
            expected_final_status="ESCALATED",
            observed_final_status=patron_incident.get("final_status") if patron_incident else None,
        )

    def cleanup(self, context: ScenarioContext) -> None:
        state = context.docker.inspect(context.target_container)
        if is_simulation_resource(state, context.scenario_id):
            context.docker.update_restart_policy(context.target_container, "no")
            context.docker.remove_container(context.target_container)

    def failure_confirmed(self, context: ScenarioContext) -> bool:
        return restart_threshold_crossed(context.docker.inspect(context.target_container), self.restart_threshold)

    def expected_failure(self) -> str:
        return f"restart_count>={self.restart_threshold}"


def restart_threshold_crossed(state, threshold: int = 3) -> bool:
    return state.exists and state.restart_count >= threshold
