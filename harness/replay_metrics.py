"""Semantic report counts from a successfully matched exact replay."""


def exact_metrics(records: list[dict]) -> dict:
    from .triggers import default_trigger_registry

    counts = {trigger.incident_type: {"positive_samples": 0, "total_samples": 0,
        "classification_agreements": 0, "terminal_outcomes": 0,
        "final_state_agreements": 0} for trigger in default_trigger_registry().triggers}
    policy_denials = 0
    for record in records:
        if record["event"] == "trigger":
            packet = record["payload"]["packet"]
            for kind, stats in counts.items():
                stats["total_samples"] += 1
                stats["classification_agreements"] += 1
                stats["positive_samples"] += int(bool(packet and packet["incident_type"] == kind))
        elif record["event"] == "policy":
            policy_denials += int(not record["payload"]["policy"]["allowed"])
        elif record["event"] == "cycle_end":
            result = record["payload"]["result"]
            incident = result.get("incident") or {}
            # Count completed attempts, not subsequent suppressed observations.
            if result.get("audit") and incident.get("status") in {"RESOLVED", "ESCALATED", "FAILED"}:
                stats = counts[incident["incident_type"]]
                stats["terminal_outcomes"] += 1
                stats["final_state_agreements"] += 1
    return {"per_incident_type": counts, "policy_denials": policy_denials,
        "action_differences": 0, "missed_incidents": 0, "extra_incidents": 0,
        "agreement_basis": "matched recorded events, not independent ground-truth accuracy"}
