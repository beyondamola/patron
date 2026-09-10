from __future__ import annotations

from ..collector import ContainerSnapshot
from .base import Trigger


class ContainerDiskFullTrigger(Trigger):
    incident_type = "CONTAINER_DISK_FULL"

    def __init__(self, threshold: float = 90.0) -> None:
        self.threshold = threshold

    def evaluate(self, snapshot: ContainerSnapshot) -> bool:
        return bool(snapshot.exists and snapshot.disk_usage_percent is not None and snapshot.disk_usage_percent >= self.threshold)

    def build_metadata(self, snapshot: ContainerSnapshot) -> dict:
        return {
            "reason": f"{snapshot.name} disk usage {snapshot.disk_usage_percent}% crossed threshold {self.threshold}%",
            "observed_state": "disk_full",
            "expected_state": "disk_below_threshold",
            "disk_usage_percent": snapshot.disk_usage_percent,
            "threshold": self.threshold,
        }

    def trace(self, snapshot: ContainerSnapshot) -> dict:
        result = self.evaluate(snapshot)
        return {
            "incident_type": self.incident_type,
            "disk_usage_percent": snapshot.disk_usage_percent,
            "threshold": self.threshold,
            "result": result,
            "reason": "threshold met" if result else "disk usage below threshold or unavailable",
        }

