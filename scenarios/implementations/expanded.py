from __future__ import annotations

from .utils import wait_for_audit_detection
from ..base import InjectionResult, ObservationResult, Scenario, ScenarioContext, utc_now
from ..docker_utils import is_simulation_resource, wait_until


def observe_escalation(context: ScenarioContext, injection: InjectionResult, incident_type: str) -> ObservationResult:
    detected_at = None
    escalated_at = None
    patron_incident = None

    def escalated() -> bool:
        nonlocal detected_at, escalated_at, patron_incident
        incident = wait_for_audit_detection(
            incident_type,
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
    return ObservationResult(
        detected=detected_at is not None,
        recovered=ok,
        detected_at=detected_at,
        recovered_at=escalated_at,
        final_state=state.status,
        error=None if ok else f"timed out waiting for {incident_type} escalation",
        patron_incident_id=patron_incident.get("incident_id") if patron_incident else None,
        expected_incident_type=incident_type,
        observed_incident_type=patron_incident.get("incident_type") if patron_incident else None,
        expected_final_status="ESCALATED",
        observed_final_status=patron_incident.get("final_status") if patron_incident else None,
    )


class OOMKilledScenario(Scenario):
    name = "oom_killed"
    description = "Force a memory-limited container to be OOMKilled."
    default_target = "patron-sim-oom-killed"
    incident_type = "CONTAINER_OOM_KILLED"

    def setup(self, context: ScenarioContext) -> None:
        context.docker.create_oom_container(context.target_container, context.labels)

    def validate_preconditions(self, context: ScenarioContext) -> None:
        if not context.docker.inspect(context.target_container).running:
            raise RuntimeError("OOM scenario target did not start")

    def inject(self, context: ScenarioContext) -> InjectionResult:
        injected_at = utc_now()
        context.docker.exec(context.target_container, ["touch", "/tmp/inject-oom"])
        observed = wait_until(lambda: self.failure_confirmed(context), min(20, context.timeout_seconds), context.poll_interval_seconds)
        return InjectionResult(True, observed, injected_at, utc_now())

    def observe(self, context: ScenarioContext, injection: InjectionResult) -> ObservationResult:
        return observe_escalation(context, injection, self.incident_type)

    def cleanup(self, context: ScenarioContext) -> None:
        state = context.docker.inspect(context.target_container)
        if is_simulation_resource(state, context.scenario_id):
            context.docker.remove_container(context.target_container)

    @staticmethod
    def failure_confirmed(context: ScenarioContext) -> bool:
        state = context.docker.inspect(context.target_container)
        return bool(state.exists and state.oom_killed)


class HighCPUScenario(Scenario):
    name = "high_cpu"
    description = "Start a bounded CPU-burning process inside a running container."
    default_target = "patron-sim-high-cpu"
    incident_type = "CONTAINER_HIGH_CPU"

    def setup(self, context: ScenarioContext) -> None:
        context.docker.create_cpu_container(context.target_container, context.labels)

    def validate_preconditions(self, context: ScenarioContext) -> None:
        if not context.docker.inspect(context.target_container).running:
            raise RuntimeError("CPU scenario target did not start")

    def inject(self, context: ScenarioContext) -> InjectionResult:
        injected_at = utc_now()
        context.docker.run(["exec", "-d", context.target_container, "sh", "-c", "timeout 90 sh -c 'while :; do :; done'"])
        observed = wait_until(lambda: self.failure_confirmed(context), min(15, context.timeout_seconds), context.poll_interval_seconds)
        return InjectionResult(True, observed, injected_at, utc_now())

    def observe(self, context: ScenarioContext, injection: InjectionResult) -> ObservationResult:
        return observe_escalation(context, injection, self.incident_type)

    def cleanup(self, context: ScenarioContext) -> None:
        state = context.docker.inspect(context.target_container)
        if is_simulation_resource(state, context.scenario_id):
            context.docker.remove_container(context.target_container)

    @staticmethod
    def failure_confirmed(context: ScenarioContext) -> bool:
        cpu = context.docker.cpu_percent(context.target_container)
        return bool(cpu is not None and cpu >= context.detector_config.cpu_threshold)


class DiskFullScenario(Scenario):
    name = "disk_full"
    description = "Fill a bounded tmpfs path inside a scenario-owned container."
    default_target = "patron-sim-disk-full"
    incident_type = "CONTAINER_DISK_FULL"

    def setup(self, context: ScenarioContext) -> None:
        context.docker.create_disk_container(context.target_container, context.labels)

    def validate_preconditions(self, context: ScenarioContext) -> None:
        if not context.docker.inspect(context.target_container).running:
            raise RuntimeError("disk scenario target did not start")

    def inject(self, context: ScenarioContext) -> InjectionResult:
        injected_at = utc_now()
        context.docker.exec(context.target_container, ["sh", "-c", "dd if=/dev/zero of=/patron-disk/fill bs=1M count=15 || true"])
        observed = wait_until(lambda: self.failure_confirmed(context), min(10, context.timeout_seconds), context.poll_interval_seconds)
        return InjectionResult(True, observed, injected_at, utc_now())

    def observe(self, context: ScenarioContext, injection: InjectionResult) -> ObservationResult:
        return observe_escalation(context, injection, self.incident_type)

    def cleanup(self, context: ScenarioContext) -> None:
        state = context.docker.inspect(context.target_container)
        if is_simulation_resource(state, context.scenario_id):
            context.docker.remove_container(context.target_container)

    @staticmethod
    def failure_confirmed(context: ScenarioContext) -> bool:
        usage = context.docker.disk_usage_percent(context.target_container, "/patron-disk")
        return bool(usage is not None and usage >= 90.0)


class BadConfigScenario(Scenario):
    name = "bad_config"
    description = "Replace valid app config with invalid content and confirm config-error logs."
    default_target = "patron-sim-bad-config"
    incident_type = "CONTAINER_BAD_CONFIG"

    def setup(self, context: ScenarioContext) -> None:
        context.docker.create_bad_config_container(context.target_container, context.labels)

    def validate_preconditions(self, context: ScenarioContext) -> None:
        if not context.docker.inspect(context.target_container).running:
            raise RuntimeError("bad-config target did not start")

    def inject(self, context: ScenarioContext) -> InjectionResult:
        injected_at = utc_now()
        context.docker.exec(context.target_container, ["sh", "-c", "echo invalid > /tmp/app.conf"])
        observed = wait_until(lambda: self.failure_confirmed(context), min(10, context.timeout_seconds), context.poll_interval_seconds)
        return InjectionResult(True, observed, injected_at, utc_now())

    def observe(self, context: ScenarioContext, injection: InjectionResult) -> ObservationResult:
        return observe_escalation(context, injection, self.incident_type)

    def cleanup(self, context: ScenarioContext) -> None:
        state = context.docker.inspect(context.target_container)
        if is_simulation_resource(state, context.scenario_id):
            context.docker.remove_container(context.target_container)

    @staticmethod
    def failure_confirmed(context: ScenarioContext) -> bool:
        state = context.docker.inspect(context.target_container)
        logs = context.docker.run(["logs", "--tail", "20", context.target_container]).stdout
        return state.exists and not state.running and "CONFIG_ERROR" in logs


class DependencyDownScenario(Scenario):
    name = "dependency_down"
    description = "Stop a scenario-owned dependency while the app remains running."
    default_target = "patron-sim-dependency-app"
    dependency_target = "patron-sim-dependency-service"
    incident_type = "CONTAINER_DEPENDENCY_DOWN"

    def setup(self, context: ScenarioContext) -> None:
        self.dependency_name = f"{context.target_container}-service"
        self.network_name = f"{context.target_container}-net"
        context.docker.create_dependency_environment(context.target_container, self.dependency_name, self.network_name, context.labels)
        wait_until(lambda: context.docker.inspect(context.target_container).health == "healthy", min(20, context.timeout_seconds), context.poll_interval_seconds)

    def validate_preconditions(self, context: ScenarioContext) -> None:
        state = context.docker.inspect(context.target_container)
        if not state.running or state.health != "healthy":
            raise RuntimeError("dependency app did not become healthy")

    def inject(self, context: ScenarioContext) -> InjectionResult:
        injected_at = utc_now()
        context.docker.stop_container(self.dependency_name)
        observed = wait_until(lambda: self.failure_confirmed(context), min(20, context.timeout_seconds), context.poll_interval_seconds)
        return InjectionResult(True, observed, injected_at, utc_now())

    def observe(self, context: ScenarioContext, injection: InjectionResult) -> ObservationResult:
        return observe_escalation(context, injection, self.incident_type)

    def cleanup(self, context: ScenarioContext) -> None:
        for name in [context.target_container, getattr(self, "dependency_name", self.dependency_target)]:
            state = context.docker.inspect(name)
            if is_simulation_resource(state, context.scenario_id):
                context.docker.remove_container(name)
        context.docker.remove_owned_network(getattr(self, "network_name", f"{context.target_container}-net"), context.scenario_id)

    def failure_confirmed(self, context: ScenarioContext) -> bool:
        app = context.docker.inspect(context.target_container)
        dep = context.docker.inspect(getattr(self, "dependency_name", self.dependency_target))
        return bool(app.exists and app.running and app.health == "unhealthy" and dep.exists and not dep.running)
