from __future__ import annotations

from ..collector import ContainerSnapshot
from .base import Trigger


class ContainerOOMKilledTrigger(Trigger):
    incident_type = "CONTAINER_OOM_KILLED"

    def evaluate(self, snapshot: ContainerSnapshot) -> bool:
        return bool(snapshot.exists and snapshot.oom_killed)

    def build_metadata(self, snapshot: ContainerSnapshot) -> dict:
        return {
            "reason": f"{snapshot.name} was OOMKilled",
            "observed_state": "oom_killed",
            "expected_state": "not_oom_killed",
            "oom_killed": snapshot.oom_killed,
            "memory_limit_bytes": snapshot.memory_limit_bytes,
        }

    def trace(self, snapshot: ContainerSnapshot) -> dict:
        result = self.evaluate(snapshot)
        return {
            "incident_type": self.incident_type,
            "oom_killed": snapshot.oom_killed,
            "result": result,
            "reason": "OOMKilled=true" if result else "OOMKilled=false",
        }

