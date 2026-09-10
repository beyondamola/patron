from __future__ import annotations

from ..collector import ContainerSnapshot
from .base import Trigger


class ContainerUnhealthyTrigger(Trigger):
    incident_type = "CONTAINER_UNHEALTHY"

    def evaluate(self, snapshot: ContainerSnapshot) -> bool:
        return bool(snapshot.exists and snapshot.running and snapshot.health == "unhealthy")

    def build_metadata(self, snapshot: ContainerSnapshot) -> dict:
        return {
            "reason": f"{snapshot.name} healthcheck is unhealthy",
            "observed_state": "unhealthy",
            "expected_state": "healthy",
            "status": snapshot.status,
            "health": snapshot.health,
            "exit_code": snapshot.exit_code,
            "restart_count": snapshot.restart_count,
        }

    def trace(self, snapshot: ContainerSnapshot) -> dict:
        result = self.evaluate(snapshot)
        if not snapshot.has_healthcheck:
            reason = "no healthcheck present"
        elif not snapshot.running:
            reason = "container is not running"
        elif snapshot.health != "unhealthy":
            reason = f"health is {snapshot.health or 'none'}"
        else:
            reason = "running and unhealthy"
        return {
            "incident_type": self.incident_type,
            "running": snapshot.running,
            "health_status": snapshot.health or "none",
            "has_healthcheck": snapshot.has_healthcheck,
            "result": result,
            "reason": reason,
        }
