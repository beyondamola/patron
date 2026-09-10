from __future__ import annotations

import json
from typing import Any


class RulePlanner:
    """Deterministic planner used before external LLM integration."""

    def plan_json(self, context: dict[str, Any]) -> str:
        container_name = context["resource"]
        incident_type = context["incident_type"]
        escalate_reasons = {
            "CONTAINER_RESTART_LOOP": (
                f"{container_name} restart count {context.get('restart_count')} "
                "indicates a likely crash loop; automated restart is not safe."
            ),
            "CONTAINER_OOM_KILLED": (
                f"{container_name} was OOMKilled; memory limit, leak, or workload investigation is required."
            ),
            "CONTAINER_HIGH_CPU": (
                f"{container_name} has high CPU usage; diagnostics are required before remediation."
            ),
            "CONTAINER_DISK_FULL": (
                f"{container_name} disk usage is high; cleanup can be destructive and requires review."
            ),
            "CONTAINER_BAD_CONFIG": (
                f"{container_name} appears to have invalid configuration; restarting will not fix bad config."
            ),
            "CONTAINER_DEPENDENCY_DOWN": (
                f"{container_name} depends on an unavailable service; the app is likely a symptom."
            ),
        }
        if incident_type in escalate_reasons:
            plan = {
                "decision": "escalate",
                "reason": escalate_reasons[incident_type],
                "confidence": 0.99,
            }
        elif incident_type == "CONTAINER_UNHEALTHY":
            plan = {
                "decision": "restart_container",
                "reason": f"{container_name} is running but health status is unhealthy.",
                "confidence": 0.95,
            }
        else:
            plan = {
                "decision": "restart_container",
                "reason": f"{container_name} is expected to be running but is not running.",
                "confidence": 0.97,
            }
        return json.dumps(plan, sort_keys=True)

    def plan(self, context: dict[str, Any]) -> dict[str, Any]:
        return json.loads(self.plan_json(context))


LLMPlanner = RulePlanner
