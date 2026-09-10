from __future__ import annotations

from ..collector import ContainerSnapshot
from .base import Trigger


class ContainerDependencyDownTrigger(Trigger):
    incident_type = "CONTAINER_DEPENDENCY_DOWN"

    def evaluate(self, snapshot: ContainerSnapshot) -> bool:
        patterns = snapshot.error_patterns or []
        return bool(snapshot.exists and (snapshot.dependency_status == "down" or "dependency_down" in patterns))

    def build_metadata(self, snapshot: ContainerSnapshot) -> dict:
        return {
            "reason": f"{snapshot.name} dependency is unavailable",
            "observed_state": "dependency_down",
            "expected_state": "dependency_available",
            "dependency_status": snapshot.dependency_status,
            "error_patterns": snapshot.error_patterns or [],
        }

    def trace(self, snapshot: ContainerSnapshot) -> dict:
        result = self.evaluate(snapshot)
        return {
            "incident_type": self.incident_type,
            "dependency_status": snapshot.dependency_status,
            "error_patterns": snapshot.error_patterns or [],
            "result": result,
            "reason": "dependency down evidence present" if result else "dependency evidence absent",
        }

