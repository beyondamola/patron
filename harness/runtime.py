from __future__ import annotations

import signal
from pathlib import Path
from typing import Any

from .audit import AuditLogger
from .capture import CaptureError, CaptureWriter
from .collector import Collector, DockerCollector
from .config import DetectorConfig
from .context_manager import build_context
from .control import IncidentControl
from .executor import DockerExecutor
from .incident import ESCALATED, FAILED, OPEN, RESOLVED, RUNNING, Incident, IncidentRegistry
from .observability import stage, trace_packet
from .planner import RulePlanner
from .policy import validate_plan
from .trigger import TriggerRegistry, default_trigger_registry
from .verifier import VerificationResult, verify_incident


MAX_RETRIES = 3


class PatronRuntime:
    def __init__(
        self,
        container_name: str = "mvp-nginx",
        dry_run: bool = False,
        verbose: bool = False,
        trace: bool = False,
        collector: Collector | None = None,
        registry: IncidentRegistry | None = None,
        audit_logger: AuditLogger | None = None,
        verifier=verify_incident,
        triggers: TriggerRegistry | None = None,
        config: DetectorConfig | None = None,
        planner=None,
        executor=None,
        capture_path: str | Path | None = None,
    ) -> None:
        self.container_name = container_name
        self.dry_run = dry_run
        self.verbose = verbose
        self.trace = trace
        self.config = config or DetectorConfig()
        self.collector = collector or DockerCollector(container_name, config=self.config)
        self.registry = registry or IncidentRegistry()
        self.clock = self.registry.clock
        self.audit_logger = audit_logger or AuditLogger(self.registry.audit_path or "logs/incidents.jsonl")
        self.registry.audit_path = str(self.audit_logger.path.resolve())
        self.planner = planner if planner is not None else RulePlanner()
        self.executor = executor if executor is not None else DockerExecutor()
        self.verifier = verifier
        self.triggers = triggers or default_trigger_registry(config=self.config, clock=self.clock.monotonic)
        self.capture_path = Path(capture_path).resolve() if capture_path else None
        self.capture = None
        self._observation_id = None
        self._capture_incident_id = None
        if self.capture_path in {self.registry.state_path, self.audit_logger.path.resolve()}:
            raise ValueError("capture must be separate from state and incident audit")

    def _start_capture(self) -> None:
        if self.capture_path is not None and self.capture is None:
            self.capture = CaptureWriter(self.capture_path, config=self.config,
                initial_state=self.registry.export_state(), clock=self.clock,
                runtime_settings={"target": self.container_name, "dry_run": self.dry_run,
                                  "cooldown_seconds": self.registry.cooldown_seconds})

    def _emit(self, event: str, payload: dict) -> None:
        if self.capture is not None:
            try:
                self.capture.emit(event, payload, observation_id=self._observation_id,
                                  incident_id=self._capture_incident_id)
            except Exception as exc:
                raise CaptureError(f"capture write failed: {exc}") from exc

    def finish_capture(self, *, complete: bool = True) -> None:
        if self.capture is not None:
            try:
                if complete:
                    self._emit("run_end", {"state": self.registry.export_state()})
            finally:
                self.capture.close()

    def _verify(self, name, incident_type, decision, **kwargs):
        if self.capture is not None and self.verifier is verify_incident:
            def observed(snapshot):
                try:
                    self.capture.observe(snapshot, verification=True,
                        observation_id=self._observation_id, incident_id=self._capture_incident_id)
                except Exception as exc:
                    raise CaptureError(f"verifier capture failed: {exc}") from exc
            result = self.verifier(name, incident_type, decision, clock=self.clock,
                                   on_observation=observed, **kwargs)
        else:
            result = self.verifier(name, incident_type, decision, **kwargs)
        self._emit("verification", {"decision": decision, "incident_type": incident_type,
                                    "result": result.to_dict(), "incident_status": kwargs.get("incident_status")})
        return result

    def process_once(self) -> dict[str, Any]:
        trace_packet("detector configuration", {"settings": self.config.to_dict(),
                     "fingerprint": self.config.fingerprint}, self.trace)
        with self.registry.lock.acquire():
            self.registry.check_revision()
            self._start_capture()
            self._observation_id = self._capture_incident_id = None
            self._emit("cycle_start", {"dry_run": self.dry_run})
            IncidentControl(self.registry, self.audit_logger,
                observer=(lambda payload: self._emit("control", payload)) if self.capture else None).process_pending()
            result = self._process_owned()
            self._emit("cycle_end", {"result": result, "state": self.registry.export_state()})
            return result

    def _process_owned(self) -> dict[str, Any]:
        try:
            return self._process_once()
        except CaptureError:
            raise
        except Exception as exc:
            incident = self.registry.active_for(self.container_name)
            if incident:
                self.registry.mark_final(incident, FAILED)
            self.audit_logger.log({
                "event": "runtime_error", "error": str(exc),
                "resource": self.container_name,
                "incident_id": incident.incident_id if incident else None,
                "final_status": FAILED,
            })
            self.registry.persist()
            stage("Runtime", f"Cycle failed: {exc}", True)
            return {"triggered": False, "error": str(exc)}

    def _process_once(self) -> dict[str, Any]:
        cycle_started = self.clock.monotonic()
        snapshot = self.collector.collect()
        if self.capture is not None:
            try:
                self._observation_id = self.capture.observe(snapshot)
            except Exception as exc:
                raise CaptureError(f"observation capture failed: {exc}") from exc
        trigger_packet, trigger_traces = self.triggers.evaluate_with_trace(snapshot)
        self._emit("trigger", {"packet": trigger_packet, "traces": trigger_traces})
        for trigger_trace in trigger_traces:
            trace_packet(f"TriggerTrace {trigger_trace['incident_type']}", trigger_trace, self.trace)
        if not snapshot.exists:
            stage("Collector", f"Cannot observe {snapshot.name}: {snapshot.status}", True)
            return {"triggered": False, "error": snapshot.status, "snapshot_status": snapshot.status}
        if self.registry.observe_generation(snapshot.name, snapshot.container_id):
            previous = self.registry.incidents.get(snapshot.name)
            if previous and not self.registry.matches_generation(previous) and previous.status not in {RESOLVED, ESCALATED, FAILED}:
                self.registry.mark_final(previous, FAILED)
                self.audit_logger.log(self._audit_record(previous,
                    {"reason": "container generation replaced before recovery"}, None, None, None, None))
            self.registry.persist()
        stage(
            "Collector",
            (
                f"target={snapshot.name} status={snapshot.status} running={snapshot.running} "
                f"health={snapshot.health or 'none'} restart_count={snapshot.restart_count}"
            ),
            self.verbose,
        )

        detection_latency = self.clock.monotonic() - cycle_started
        trace_packet("trigger packet", trigger_packet or {"incident_type": None}, self.trace)

        active = self.registry.active_for(snapshot.name)
        if trigger_packet is None:
            stage("Trigger", "no incident", self.verbose)
            if active:
                self._capture_incident_id = active.incident_id
                result = self._verify(snapshot.name, active.incident_type, "restart_container")
                if not result.passed:
                    return {"triggered": False, "healthy": False, "snapshot_status": snapshot.status}
                self.registry.mark_resolved(active)
                active.verification_state = result.to_dict()
                resolved_packet = {
                    "incident_type": active.incident_type,
                    "reason": "resource returned to expected state",
                }
                self.audit_logger.log(self._audit_record(active, resolved_packet, None, None, None, None))
                self.registry.persist()
                self._emit("transition", {"incident": active.to_dict()})
                stage("Audit", "incident logged", self.verbose)
            return {
                "triggered": False,
                "status": RESOLVED if active else None,
                "resource": snapshot.name,
                "snapshot_status": snapshot.status,
                "healthy": snapshot.exists and snapshot.running,
            }

        stage("Trigger", f"INCIDENT: {trigger_packet['incident_type']}", self.verbose)
        incident, created = self.registry.get_or_open(
            trigger_packet["resource"],
            trigger_packet["resource_type"],
            trigger_packet["incident_type"],
            trigger_packet["reason"],
            container_id=snapshot.container_id,
        )
        if incident is None:
            stage("Trigger", "suppressed by cooldown", self.verbose)
            return {"triggered": False, "cooldown": True}
        if created:
            stage("Incident", f"opened {incident.incident_id}", self.verbose)
        else:
            stage("Incident", f"reusing {incident.incident_id}", self.verbose)

        incident.status = RUNNING
        incident.touch(self.clock)
        self._capture_incident_id = incident.incident_id
        self._emit("transition", {"incident": incident.to_dict(), "created": created})

        context = build_context(snapshot, incident, trigger_packet)
        self._emit("context", {"context": context})
        stage("Context", "status collected; logs collected", self.verbose)
        trace_packet("context packet", context, self.trace)

        planning_started = self.clock.monotonic()
        plan = self.planner.plan(context)
        planning_latency = self.clock.monotonic() - planning_started
        self._emit("plan", {"plan": plan})
        incident.last_action = plan.get("decision")
        stage("Planner", str(plan.get("decision")), self.verbose)
        trace_packet("planner JSON", plan, self.trace)

        policy = validate_plan(plan, context)
        self._emit("policy", {"policy": policy.to_dict()})
        stage("Policy", "APPROVED" if policy.allowed else "DENY", self.verbose)
        trace_packet("policy output", policy.to_dict(), self.trace)

        execution: dict[str, Any] | None = None
        verification: VerificationResult | None = None
        execution_latency = None
        verification_latency = None

        if not policy.allowed:
            execution = {"skipped": True, "reason": "policy_denied", "success": False}
            verification = VerificationResult(
                checked=False,
                running=False,
                exit_status=None,
                health="not_checked",
                passed=False,
            )
            incident.verification_state = verification.to_dict()
            trace_packet("executor response", execution, self.trace)
            trace_packet("verifier response", verification.to_dict(), self.trace)
            self.registry.mark_final(incident, FAILED)
        elif self.dry_run:
            execution = {"skipped": True, "reason": "dry_run", "success": False}
            verification = VerificationResult(
                checked=False,
                running=False,
                exit_status=None,
                health="not_checked",
                passed=False,
            )
            incident.verification_state = verification.to_dict()
            incident.status = OPEN
            incident.touch(self.clock)
            stage("Executor", "dry run: skipped", self.verbose)
            trace_packet("executor response", execution, self.trace)
            stage("Verifier", "SKIPPED", self.verbose)
            trace_packet("verifier response", verification.to_dict(), self.trace)
        else:
            execution_started = self.clock.monotonic()
            self._emit("action_requested", {"plan": plan, "resource": context["resource"]})
            execution = self.executor.execute(plan, context)
            self._emit("execution", {"result": execution})
            execution_latency = self.clock.monotonic() - execution_started
            if plan["decision"] == "escalate":
                stage("Executor", f"escalate {context['resource']}", self.verbose)
            else:
                stage("Executor", f"docker restart {context['resource']}", self.verbose)
            trace_packet("executor response", execution, self.trace)

            verification_started = self.clock.monotonic()
            if plan["decision"] == "escalate" and execution.get("success"):
                self.registry.mark_final(incident, ESCALATED)
                verification = self._verify(context["resource"], incident.incident_type, plan["decision"], incident_status=incident.status)
            else:
                verification = self._verify(context["resource"], incident.incident_type, plan["decision"])
            verification_latency = self.clock.monotonic() - verification_started
            incident.verification_state = verification.to_dict()
            stage("Verifier", "PASS" if verification.passed else "FAIL", self.verbose)
            trace_packet("verifier response", verification.to_dict(), self.trace)

            if plan["decision"] == "escalate" and execution.get("success") and verification.passed:
                self.registry.mark_final(incident, ESCALATED)
            elif execution.get("success") and verification.passed:
                self.registry.mark_resolved(incident)
            else:
                incident.attempts += 1
                if incident.attempts >= MAX_RETRIES:
                    self.registry.mark_final(incident, ESCALATED)
                else:
                    incident.status = OPEN
                    incident.touch(self.clock)

        if execution and execution.get("skipped"):
            self._emit("execution", {"result": execution})
            self._emit("verification", {"decision": plan.get("decision"),
                "incident_type": incident.incident_type, "result": verification.to_dict(),
                "incident_status": incident.status})
        metrics = {
            "incident_type": incident.incident_type,
            "detection_latency_seconds": None,
            "collection_trigger_latency_seconds": detection_latency,
            "planning_latency_seconds": planning_latency,
            "execution_latency_seconds": execution_latency,
            "verification_latency_seconds": verification_latency,
            "attempts": incident.attempts,
            "final_status": incident.status,
        }
        record = self._audit_record(
            incident,
            trigger_packet,
            context,
            plan,
            policy.to_dict(),
            execution,
            verification,
            metrics,
        )
        self.audit_logger.log(record)
        self.registry.persist()
        self._emit("transition", {"incident": incident.to_dict()})
        stage("Audit", "incident logged", self.verbose)
        return {"triggered": True, "incident": incident.to_dict(), "audit": record}

    def watch(self, interval: int = 10) -> int:
        self.config.validate_interval(interval)
        complete = False
        try:
            with self.registry.lock.acquire():
                self.registry.check_revision()
                result = self._watch_owned(interval)
                complete = True
                return result
        finally:
            self.finish_capture(complete=complete)

    def _watch_owned(self, interval: int) -> int:
        stage("Runtime", f"watching every {interval}s", True)
        shutdown_requested = False
        previous_handler = signal.getsignal(signal.SIGINT)

        def request_shutdown(signum, frame) -> None:
            nonlocal shutdown_requested
            shutdown_requested = True

        signal.signal(signal.SIGINT, request_shutdown)
        try:
            while not shutdown_requested:
                self.process_once()
                slept = 0.0
                while slept < interval and not shutdown_requested:
                    self.clock.sleep(min(0.5, interval - slept))
                    slept += 0.5
        finally:
            signal.signal(signal.SIGINT, previous_handler)
            stage("Runtime", "shutdown requested; persisting incident state", True)
            self.registry.persist()
        stage("Runtime", "shutdown complete", True)
        return 0

    def _audit_record(
        self,
        incident: Incident,
        trigger_packet: dict[str, Any],
        context: dict[str, Any] | None,
        plan: dict[str, Any] | None,
        policy: dict[str, Any] | None,
        execution: dict[str, Any] | None,
        verification: VerificationResult | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "detector_config": self.config.to_dict(),
            "detector_config_fingerprint": self.config.fingerprint,
            "event": "incident_snapshot",
            "state_path": str(self.registry.state_path),
            "incident": incident.to_dict(),
            "incident_id": incident.incident_id,
            "incident_type": incident.incident_type,
            "timestamps": {
                "created_at": incident.created_at,
                "updated_at": incident.updated_at,
            },
            "trigger_reason": trigger_packet.get("reason"),
            "context_summary": {
                "resource": context.get("resource") if context else incident.resource,
                "observed_state": context.get("observed_state") if context else None,
                "expected_state": context.get("expected_state") if context else "running",
                "risk_level": context.get("risk_level") if context else "low",
            },
            "planner_output": plan,
            "policy_result": policy,
            "action_executed": execution,
            "verification_result": verification.to_dict() if verification else incident.verification_state,
            "retry_count": incident.attempts,
            "final_status": incident.status,
            "metrics": metrics or {
                "incident_type": incident.incident_type,
                "detection_latency_seconds": None,
                "planning_latency_seconds": None,
                "execution_latency_seconds": None,
                "verification_latency_seconds": None,
                "attempts": incident.attempts,
                "final_status": incident.status,
            },
            "dry_run": self.dry_run,
        }
