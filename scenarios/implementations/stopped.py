from __future__ import annotations

from .utils import seconds_between, wait_for_audit_detection
from ..base import InjectionResult, ObservationResult, Scenario, ScenarioContext, utc_now
from ..docker_utils import is_simulation_resource, wait_until


class StoppedContainerScenario(Scenario):
    name = "stopped"
    description = "Stop a running Docker container and wait for Patron to restart it."
    default_target = "patron-sim-stopped"
    incident_type = "CONTAINER_STOPPED"

    def setup(self, context: ScenarioContext) -> None:
        context.narrate(f"Preparing scenario: {self.name}")
        context.narrate(f"Creating container {context.target_container}")
        context.docker.create_nginx_container(context.target_container, context.labels)
        context.narrate(f"Target container {context.target_container} is running")

    def validate_preconditions(self, context: ScenarioContext) -> None:
        state = context.docker.inspect(context.target_container)
        if not state.exists or not state.running:
            raise RuntimeError(f"{context.target_container} must be running before injection")

    def inject(self, context: ScenarioContext) -> InjectionResult:
        context.narrate("Injecting failure: stopping container")
        injected_at = utc_now()
        context.docker.stop_container(context.target_container)
        observed = wait_until(
            lambda: self.failure_confirmed(context),
            timeout_seconds=min(10, context.timeout_seconds),
            poll_interval_seconds=context.poll_interval_seconds,
        )
        if observed:
            context.narrate("Failure confirmed: container is exited")
        return InjectionResult(injected=True, observed=observed, injected_at=injected_at, observed_at=utc_now())

    def observe(self, context: ScenarioContext, injection: InjectionResult) -> ObservationResult:
        context.narrate("Waiting for Patron recovery")
        detected_at = None
        recovered_at = None
        patron_incident = None
        deadline_seconds = context.timeout_seconds

        def recovered() -> bool:
            nonlocal detected_at, recovered_at, patron_incident
            incident = wait_for_audit_detection(
                self.incident_type,
                context.target_container,
                injection.injected_at or context.started_at,
                return_record=True,
            )
            patron_incident = incident or patron_incident
            detected_at = detected_at or ((incident.get("timestamps") or {}).get("updated_at") if incident else None)
            state = context.docker.inspect(context.target_container)
            if state.running:
                recovered_at = recovered_at or utc_now()
            return bool(incident and incident.get("final_status") == "RESOLVED" and state.running)

        ok = wait_until(recovered, deadline_seconds, context.poll_interval_seconds)
        state = context.docker.inspect(context.target_container)
        if ok:
            context.narrate("Recovery observed: container is running")
        return ObservationResult(
            detected=detected_at is not None,
            recovered=ok,
            detected_at=detected_at,
            recovered_at=recovered_at,
            final_state=state.status,
            error=None if ok else "timed out waiting for stopped-container recovery",
            patron_incident_id=patron_incident.get("incident_id") if patron_incident else None,
            expected_incident_type=self.incident_type,
            observed_incident_type=patron_incident.get("incident_type") if patron_incident else None,
            expected_final_status="RESOLVED",
            observed_final_status=patron_incident.get("final_status") if patron_incident else None,
        )

    def cleanup(self, context: ScenarioContext) -> None:
        state = context.docker.inspect(context.target_container)
        if is_simulation_resource(state, context.scenario_id):
            context.docker.remove_container(context.target_container)

    @staticmethod
    def failure_confirmed(context: ScenarioContext) -> bool:
        state = context.docker.inspect(context.target_container)
        return state.exists and not state.running and state.status == "exited"

    @staticmethod
    def expected_failure() -> str:
        return "running=false status=exited"

    @staticmethod
    def latencies(injection: InjectionResult, observation: ObservationResult) -> tuple[float | None, float | None]:
        return (
            seconds_between(injection.injected_at, observation.detected_at),
            seconds_between(injection.injected_at, observation.recovered_at),
        )
