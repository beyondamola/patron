from __future__ import annotations

from ..collector import ContainerSnapshot
from .base import Trigger


class ContainerRestartLoopTrigger(Trigger):
    incident_type = "CONTAINER_RESTART_LOOP"

    def __init__(self, restart_threshold: int = 3) -> None:
        self.restart_threshold = restart_threshold

    def evaluate(self, snapshot: ContainerSnapshot) -> bool:
        return bool(snapshot.exists and snapshot.restart_count >= self.restart_threshold)

    def build_metadata(self, snapshot: ContainerSnapshot) -> dict:
        return {
            "reason": (
                f"{snapshot.name} restart count {snapshot.restart_count} "
                f"crossed threshold {self.restart_threshold}"
            ),
            "observed_state": "restart_loop",
            "expected_state": "stable",
            "status": snapshot.status,
            "exit_code": snapshot.exit_code,
            "health": snapshot.health,
            "restart_count": snapshot.restart_count,
            "restart_threshold": self.restart_threshold,
        }

    def trace(self, snapshot: ContainerSnapshot) -> dict:
        result = self.evaluate(snapshot)
        return {
            "incident_type": self.incident_type,
            "restart_count": snapshot.restart_count,
            "threshold": self.restart_threshold,
            "result": result,
            "reason": "threshold met" if result else "restart count below threshold",
        }
