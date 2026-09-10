from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


ALLOWED_ACTIONS = {"restart_container", "escalate"}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_plan(plan: dict[str, Any], context: dict[str, Any]) -> PolicyDecision:
    if not isinstance(plan, dict):
        return PolicyDecision(False, "plan must be an object")
    action = plan.get("decision")
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
        return PolicyDecision(False, f"action {action!r} is not allowlisted")

    if action not in context.get("allowed_actions", []):
        return PolicyDecision(False, f"action {action!r} is not allowed by context")

    if action == "restart_container" and context.get("incident_type", "CONTAINER_STOPPED") not in {"CONTAINER_STOPPED", "CONTAINER_UNHEALTHY"}:
        return PolicyDecision(False, "this incident requires escalation")

    return PolicyDecision(True, "plan is allowlisted")
