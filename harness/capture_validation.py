"""Semantic checks for recorded evidence, without filesystem or Docker access."""
from __future__ import annotations

import math

from .capture import SNAPSHOT_FIELDS
from .collector import parse_timestamp
from .control import ControlRequest, validate_control_envelope
from .incident import Incident
from .policy import ALLOWED_ACTIONS


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"invalid capture: {message}")


def validate_state(state: dict) -> None:
    require(isinstance(state, dict), "state must be an object")
    require(type(state.get("schema_version")) is int and state["schema_version"] == 1, "state schema")
    require(type(state.get("revision")) is int and state["revision"] >= 0, "state revision")
    for key in ("incidents", "resolved_at", "control_results", "outbox", "observed_generations",
                "resolved_generations", "resolved_incident_types"):
        require(isinstance(state.get(key), dict), f"missing state {key}")
    for name, value in state["incidents"].items():
        require(isinstance(value, dict), "incident must be an object")
        try:
            incident = Incident.from_dict(value)
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(f"invalid capture incident: {exc}") from exc
        require(incident.resource == name, "incident resource key mismatch")
    for stamp in state["resolved_at"].values():
        require(parse_timestamp(stamp) is not None, "resolved timestamp")
    for key in ("observed_generations", "resolved_incident_types"):
        require(all(isinstance(name, str) and isinstance(value, str) and value
                    for name, value in state[key].items()), f"state {key} values")
    require(all(isinstance(name, str) and (value is None or isinstance(value, str))
                for name, value in state["resolved_generations"].items()), "resolved generation values")
    outbox_path = "capture"
    if state["outbox"]:
        first = next(iter(state["outbox"].values()))
        require(isinstance(first, dict) and isinstance(first.get("state_path"), str), "outbox state reference")
        outbox_path = first["state_path"]
    validate_control_envelope(state["control_results"], state["outbox"], outbox_path)


def validate_snapshot(snapshot: dict) -> None:
    require(isinstance(snapshot, dict) and set(snapshot) == set(SNAPSHOT_FIELDS), "normalized snapshot fields")
    for key in ("exists", "running", "has_healthcheck", "oom_killed"):
        require(type(snapshot[key]) is bool, f"snapshot {key} must be boolean")
    for key in ("name", "status"):
        require(isinstance(snapshot[key], str) and bool(snapshot[key]), f"snapshot {key}")
    require(type(snapshot["restart_count"]) is int and snapshot["restart_count"] >= 0, "restart count")
    for key in ("exit_code", "memory_limit_bytes", "memory_usage_bytes", "cpu_quota", "cpu_period", "nano_cpus"):
        require(snapshot[key] is None or type(snapshot[key]) is int, f"snapshot {key}")
    for key in ("cpu_percent", "disk_usage_percent", "observed_monotonic"):
        value = snapshot[key]
        require(value is None or (type(value) in (int, float) and math.isfinite(value)), f"snapshot {key}")
    for key in ("container_id", "health", "restart_policy", "network_mode", "dependency_status", "started_at"):
        require(snapshot[key] is None or isinstance(snapshot[key], str), f"snapshot {key}")
    for key in ("recent_logs", "error_patterns", "ports"):
        require(snapshot[key] is None or (isinstance(snapshot[key], list)
                and all(isinstance(value, str) for value in snapshot[key])), f"snapshot {key}")
    logs = snapshot["recent_logs"] or []
    require(len(logs) <= 20 and all(len(line) <= 1000 for line in logs), "unbounded capture logs")
    errors = snapshot["probe_errors"]
    require(errors is None or (isinstance(errors, dict) and all(isinstance(value, str) for value in errors.values())), "probe errors")


def validate_capture(records: list[dict]) -> dict:
    """Check payloads and causal ordering after read_capture envelope validation."""
    header = records[0]["payload"]
    validate_state(header.get("initial_state"))
    history = header.get("control_history", [])
    require(isinstance(history, list) and len(history) <= 1000, "control history must be a bounded list")
    for evidence in history:
        require(isinstance(evidence, dict), "control history entry must be an object")
        if set(evidence) == {"incident"}:
            incident = evidence["incident"]
            require(isinstance(incident, dict), "historical incident must be an object")
            for key in ("incident_id", "resource", "status"):
                require(isinstance(incident.get(key), str) and bool(incident[key]), f"historical incident {key}")
        else:
            require(set(evidence) == {"event", "event_id", "result"}
                    and evidence["event"] == "operator_control", "historical request result fields")
            require(isinstance(evidence["event_id"], str) and isinstance(evidence["result"], dict)
                    and evidence["result"].get("request_id") == evidence["event_id"], "historical request identity")
    known_incidents = {value["incident_id"] for value in header["initial_state"]["incidents"].values()}
    require(header.get("collector_version") == 1 and header.get("redaction_version") == 1, "collector/redaction version")
    settings = header.get("runtime_settings")
    require(isinstance(settings, dict) and isinstance(settings.get("target"), str), "runtime target")
    require(type(settings.get("dry_run")) is bool, "runtime dry_run")
    require(type(settings.get("cooldown_seconds")) is int and settings["cooldown_seconds"] >= 0, "cooldown settings")
    cycle = None
    observation = None
    incident_id = None
    context = plan = policy = execution = None
    requested = verified = triggered = False
    pending_control = None
    cycles = actions = verifier_reads = 0
    cycle_verifier_reads = 0
    for record in records[1:]:
        event, payload = record["event"], record["payload"]
        if event == "cycle_start":
            require(cycle is None, "nested cycle")
            require(type(payload.get("dry_run")) is bool and payload["dry_run"] == settings["dry_run"], "cycle dry_run")
            cycle = record["sequence"]
            observation = incident_id = context = plan = policy = execution = None
            requested = verified = triggered = False
            cycle_verifier_reads = 0
            cycles += 1
            continue
        if event == "run_end":
            require(cycle is None, "run ended inside a cycle")
            validate_state(payload.get("state"))
            continue
        require(cycle is not None, f"{event} outside cycle")
        if event == "control":
            require(observation is None, "operator action during remediation")
            try:
                request = ControlRequest(**payload["request"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid capture control request: {exc}") from exc
            if payload.get("phase") == "requested":
                require(pending_control is None, "overlapping control requests")
                pending_control = request.request_id
            else:
                require(payload.get("phase") == "applied" and pending_control == request.request_id, "unmatched control result")
                require(isinstance(payload.get("result"), dict), "control result")
                validate_state(payload.get("state"))
                pending_control = None
            continue
        require(pending_control is None, "missing control application result")
        if event == "observation":
            require(observation is None, "duplicate cycle observation")
            require(record.get("observation_id") is None, "main observation cannot have parent reference")
            validate_snapshot(payload.get("snapshot"))
            require(payload["snapshot"]["name"] == settings["target"], "observation target mismatch")
            observation = record["sequence"]
            continue
        if event == "cycle_end":
            require(isinstance(payload.get("result"), dict), "cycle result")
            require(observation is not None or payload["result"].get("error"), "cycle missing observation")
            if not payload["result"].get("error"):
                require(triggered, "cycle missing trigger evaluation")
                require(not requested or (execution is not None and verified), "missing action outcome")
                require(context is None or (plan is not None and policy is not None and execution is not None and verified), "incomplete planned cycle")
            validate_state(payload.get("state"))
            cycle = None
            continue
        require(observation is not None and record.get("observation_id") == observation, "missing or cross-cycle observation reference")
        reference = record.get("incident_id")
        if event not in {"trigger", "transition"}:
            require(isinstance(reference, str) and reference in known_incidents, "unknown incident reference")
            require(incident_id is None or reference == incident_id, "cross-incident event reference")
            incident_id = reference
        if event == "trigger":
            require(not triggered, "duplicate trigger event")
            require(isinstance(payload.get("traces"), list), "trigger traces")
            require(payload.get("packet") is None or isinstance(payload["packet"], dict), "trigger packet")
            triggered = True
        elif event == "transition":
            try:
                incident = Incident.from_dict(payload["incident"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid capture transition: {exc}") from exc
            require(incident.incident_id == record.get("incident_id"), "transition incident reference")
            require(incident.resource == settings["target"], "transition resource")
            require(incident_id is None or incident_id == incident.incident_id, "incident changed within cycle")
            incident_id = incident.incident_id
            known_incidents.add(incident_id)
        elif event == "context":
            require(context is None and triggered, "context ordering")
            context = payload.get("context")
            require(isinstance(context, dict) and context.get("incident_id") == incident_id, "context incident")
        elif event == "plan":
            require(context is not None and plan is None, "plan ordering")
            plan = payload.get("plan")
            require(isinstance(plan, dict), "plan must be an object")
        elif event == "policy":
            require(plan is not None and policy is None, "policy ordering")
            policy = payload.get("policy")
            require(isinstance(policy, dict) and type(policy.get("allowed")) is bool, "policy output")
        elif event == "action_requested":
            require(policy is not None and policy["allowed"] and not settings["dry_run"] and not requested, "action lacks authorization")
            require(payload.get("plan") == plan and payload.get("resource") == settings["target"], "action differs from plan/target")
            require(isinstance(plan.get("decision"), str) and plan["decision"] in ALLOWED_ACTIONS, "action not allowlisted")
            requested = True
            actions += 1
        elif event == "execution":
            require(execution is None and policy is not None, "execution ordering")
            execution = payload.get("result")
            require(isinstance(execution, dict) and type(execution.get("success")) is bool, "execution result")
            require(requested or execution.get("skipped") is True, "unrequested execution")
        elif event == "verification_observation":
            require(not verified and (execution is not None or context is None), "verifier read ordering")
            validate_snapshot(payload.get("snapshot"))
            require(payload["snapshot"]["name"] == settings["target"], "verifier target")
            verifier_reads += 1
            cycle_verifier_reads += 1
        elif event == "verification":
            require(not verified and (execution is not None or context is None), "verification ordering")
            result = payload.get("result")
            require(isinstance(result, dict) and all(type(result.get(key)) is bool for key in ("checked", "running", "passed")), "verification result")
            require(isinstance(result.get("health"), str) and type(result.get("restart_count")) is int, "verification health/restart count")
            require(result.get("exit_status") is None or type(result["exit_status"]) is int, "verification exit status")
            if plan is not None:
                require(payload.get("decision") == plan.get("decision"), "verification decision differs from plan")
            if payload.get("decision") == "escalate" and result["passed"]:
                require(payload.get("incident_status") == "ESCALATED", "escalation verification lacks actual state")
            if payload.get("decision") == "restart_container" and result["checked"]:
                require(cycle_verifier_reads > 0, "verification missing independent observations")
            verified = True
        else:
            raise ValueError(f"unsupported causal capture event: {event}")
    require(cycle is None and pending_control is None, "unfinished cycle/control")
    return {"cycles": cycles, "actions": actions, "verifier_observations": verifier_reads}
