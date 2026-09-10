from __future__ import annotations

from ..collector import ContainerSnapshot
from .base import Trigger


class ContainerHighCPUTrigger(Trigger):
    incident_type = "CONTAINER_HIGH_CPU"

    def __init__(self, threshold: float = 80.0) -> None:
        self.threshold = threshold

    def evaluate(self, snapshot: ContainerSnapshot) -> bool:
        return bool(snapshot.exists and snapshot.running and snapshot.cpu_percent is not None and snapshot.cpu_percent >= self.threshold)

    def build_metadata(self, snapshot: ContainerSnapshot) -> dict:
        return {
            "reason": f"{snapshot.name} CPU {snapshot.cpu_percent}% crossed threshold {self.threshold}%",
            "observed_state": "high_cpu",
            "expected_state": "cpu_below_threshold",
            "cpu_percent": snapshot.cpu_percent,
            "threshold": self.threshold,
        }

    def trace(self, snapshot: ContainerSnapshot) -> dict:
        result = self.evaluate(snapshot)
        return {
            "incident_type": self.incident_type,
            "cpu_percent": snapshot.cpu_percent,
            "threshold": self.threshold,
            "running": snapshot.running,
            "result": result,
            "reason": "threshold met" if result else "CPU below threshold or unavailable",
        }

