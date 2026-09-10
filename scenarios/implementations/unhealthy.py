from __future__ import annotations

from .utils import wait_for_audit_detection
from ..base import InjectionResult, ObservationResult, Scenario, ScenarioContext, utc_now
from ..docker_utils import is_simulation_resource, wait_until


class UnhealthyContainerScenario(Scenario):
    name = "unhealthy"
    description = "Make a running container fail its Docker health check."
    default_target = "patron-sim-unhealthy"
    incident_type = "CONTAINER_UNHEALTHY"

    def setup(self, context: ScenarioContext) -> None:
        context.narrate(f"Preparing scenario: {self.name}")
        context.docker.create_healthcheck_container(context.target_container, context.labels)
        healthy = wait_until(
            lambda: self.is_healthy(context),
            timeout_seconds=min(20, context.timeout_seconds),
            poll_interval_seconds=context.poll_interval_seconds,
        )
        if not healthy:
            raise RuntimeError("healthcheck container did not become healthy")
        context.narrate(f"Target container {context.target_container} is healthy")

    def validate_preconditions(self, context: ScenarioContext) -> None:
        if not self.is_healthy(context):
            raise RuntimeError(f"{context.target_container} must be running and healthy")

    def inject(self, context: ScenarioContext) -> InjectionResult:
        context.narrate("Injecting failure: removing healthcheck file")
        injected_at = utc_now()
        context.docker.exec(context.target_container, ["rm", "-f", "/tmp/patron-health"])
        observed = wait_until(
            lambda: self.failure_confirmed(context),
            timeout_seconds=min(20, context.timeout_seconds),
            poll_interval_seconds=context.poll_interval_seconds,
        )
        if observed:
            context.narrate("Failure confirmed: container is unhealthy")
        return InjectionResult(True, observed, injected_at, utc_now())

    def observe(self, context: ScenarioContext, injection: InjectionResult) -> ObservationResult:
        context.narrate("Waiting for Patron recovery")
        detected_at = None
        recovered_at = None
        patron_incident = None

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
            if self.is_healthy(context):
                recovered_at = recovered_at or utc_now()
            return bool(incident and incident.get("final_status") == "RESOLVED" and self.is_healthy(context))

        ok = wait_until(recovered, context.timeout_seconds, context.poll_interval_seconds)
        state = context.docker.inspect(context.target_container)
        if ok:
            context.narrate("Recovery observed: container is healthy")
        return ObservationResult(
            detected=detected_at is not None,
            recovered=ok,
            detected_at=detected_at,
            recovered_at=recovered_at,
            final_state=state.health or state.status,
            error=None if ok else "timed out waiting for unhealthy-container recovery",
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
    def expected_failure() -> str:
        return "running=true has_healthcheck=true health_status=unhealthy"

    @staticmethod
    def is_healthy(context: ScenarioContext) -> bool:
        state = context.docker.inspect(context.target_container)
        return state.exists and state.running and state.health == "healthy"

    @staticmethod
    def failure_confirmed(context: ScenarioContext) -> bool:
        state = context.docker.inspect(context.target_container)
        return state.exists and state.running and state.has_healthcheck and state.health == "unhealthy"
