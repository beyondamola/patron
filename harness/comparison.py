"""Compare recommendations on fixed observations, never simulate candidate recovery."""
from __future__ import annotations

from copy import deepcopy

from .capture import read_capture
from .capture_validation import validate_capture
from .collector import ContainerSnapshot
from .config import DetectorConfig
from .context_manager import build_context
from .incident import Incident
from .planner import RulePlanner
from .shadow import CandidatePlanner, evaluate_candidate
from .triggers import default_trigger_registry


def compare_capture(path, baseline_config: DetectorConfig, candidate_config: DetectorConfig,
                    candidate: CandidatePlanner | None = None) -> dict:
    records = read_capture(path)
    validate_capture(records)
    captured_config = DetectorConfig(**records[0]["payload"]["config"])
    for config in (baseline_config, candidate_config):
        for key in ("disk_path", "dependency", "log_evidence_seconds"):
            if getattr(config, key) != getattr(captured_config, key):
                raise ValueError(f"cannot compare changed {key}: the required probe evidence was not captured")
    now = 0.0
    baseline = default_trigger_registry(config=baseline_config, clock=lambda: now)
    proposed = default_trigger_registry(config=candidate_config, clock=lambda: now)
    planner = candidate if candidate is not None else RulePlanner()
    context_by_observation = {record["observation_id"]: record["payload"]["context"]
                              for record in records if record["event"] == "context"}
    trigger_by_observation = {record["observation_id"]: record["payload"]["packet"]
                              for record in records if record["event"] == "trigger"}
    outcomes = {record["observation_id"]: record["payload"]["result"]
                for record in records if record["event"] == "cycle_end"}
    rows = []
    divergence = False
    counts = {trigger.incident_type: {"baseline_positive": 0, "candidate_positive": 0,
        "agreement_samples": 0, "total_samples": 0, "missed": 0, "extra": 0} for trigger in baseline.triggers}
    for record in records:
        if record["event"] != "observation":
            continue
        now = record["monotonic_offset"]
        snapshot = ContainerSnapshot(**record["payload"]["snapshot"], raw={})
        baseline_packet = baseline.evaluate(snapshot)
        candidate_packet = proposed.evaluate(snapshot)
        recorded_packet = trigger_by_observation.get(record["sequence"])
        recorded_context = context_by_observation.get(record["sequence"])

        def recommendation(packet, engine):
            if packet is None:
                return None
            if recorded_context and packet["incident_type"] == recorded_context["incident_type"]:
                context = deepcopy(recorded_context)
                context["trigger"] = {key: packet[key] for key in ("incident_type", "reason", "metadata")}
            else:
                incident = Incident("comparison-only", snapshot.name, "docker_container", packet["incident_type"],
                                    "OPEN", 0, record["utc_time"], record["utc_time"])
                context = build_context(snapshot, incident, packet)
            return evaluate_candidate(engine, context)

        left = recommendation(baseline_packet, RulePlanner())
        right = recommendation(candidate_packet, planner)
        left_type = baseline_packet["incident_type"] if baseline_packet else None
        right_type = candidate_packet["incident_type"] if candidate_packet else None
        recorded_type = recorded_packet["incident_type"] if recorded_packet else None
        left_action = (left["plan"] or {}).get("decision") if left else None
        right_action = (right["plan"] or {}).get("decision") if right else None
        allowed_left = left["policy"]["allowed"] if left else None
        allowed_right = right["policy"]["allowed"] if right else None
        different = left_type != right_type or left_action != right_action or allowed_left != allowed_right
        malformed = bool(right and not right["schema_valid"])
        recorded_result = outcomes.get(record["sequence"], {})
        recorded_plan = (recorded_result.get("audit") or {}).get("planner_output")
        recorded_action = recorded_plan.get("decision") if isinstance(recorded_plan, dict) else None
        if (right_type != recorded_type or malformed or (recorded_context and
                (right_action != recorded_action or not allowed_right))):
            divergence = True
        for kind, stats in counts.items():
            stats["total_samples"] += 1
            stats["baseline_positive"] += int(left_type == kind)
            stats["candidate_positive"] += int(right_type == kind)
            stats["agreement_samples"] += int((left_type == kind) == (right_type == kind))
            stats["missed"] += int(left_type == kind and right_type != kind)
            stats["extra"] += int(left_type != kind and right_type == kind)
        incident = recorded_result.get("incident") or {}
        metrics = (recorded_result.get("audit") or {}).get("metrics") or {}
        rows.append({"observation_id": record["sequence"], "baseline_type": left_type,
            "candidate_type": right_type, "recorded_type": recorded_type,
            "baseline": left, "candidate": right, "different": different, "malformed": malformed,
            "action_different": left_action != right_action,
            "policy_different": allowed_left != allowed_right,
            "recommendation_disagreement": bool(left and right and left["plan"] != right["plan"]),
            "recorded_attempts": incident.get("attempts"), "recorded_final_status": incident.get("status"),
            "candidate_final_status": None,
            "final_state_agreement": None,
            "outcome_evidence": "counterfactual_unknown" if divergence else "recorded_reference_only",
            "detection_latency_seconds": metrics.get("detection_latency_seconds"),
            "recorded_runtime_metrics": deepcopy(metrics)})
    return {"schema_version": 1, "mode": "comparison", "execution_enabled": False,
        "scope": "per-observation recommendations; no candidate lifecycle or recovery is simulated",
        "baseline_config_fingerprint": baseline_config.fingerprint,
        "candidate_config_fingerprint": candidate_config.fingerprint,
        "per_incident_type": counts, "observations": rows,
        "regressions": sum(row["different"] or row["malformed"] for row in rows),
        "malformed_plans": sum(row["malformed"] for row in rows),
        "action_differences": sum(row["action_different"] for row in rows),
        "policy_differences": sum(row["policy_different"] for row in rows),
        "final_state_agreement": {"comparable": 0, "agreed": 0,
            "unknown": sum(row["recorded_final_status"] is not None for row in rows),
            "reason": "recommendation comparison does not execute a candidate lifecycle"},
        "policy_denials": sum(bool(row["candidate"] and not row["candidate"]["policy"]["allowed"]) for row in rows)}
