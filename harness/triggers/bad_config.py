from __future__ import annotations

from ..collector import ContainerSnapshot
from .base import Trigger


class ContainerBadConfigTrigger(Trigger):
    incident_type = "CONTAINER_BAD_CONFIG"

    def evaluate(self, snapshot: ContainerSnapshot) -> bool:
        return bool(snapshot.exists and "bad_config" in (snapshot.error_patterns or []))

    def build_metadata(self, snapshot: ContainerSnapshot) -> dict:
        return {
            "reason": f"{snapshot.name} logs indicate invalid configuration",
            "observed_state": "bad_config",
            "expected_state": "valid_config",
            "error_patterns": snapshot.error_patterns or [],
        }

    def trace(self, snapshot: ContainerSnapshot) -> dict:
        result = self.evaluate(snapshot)
        return {
            "incident_type": self.incident_type,
            "error_patterns": snapshot.error_patterns or [],
            "result": result,
            "reason": "bad_config pattern present" if result else "bad_config pattern absent",
        }

