from __future__ import annotations

from ..collector import ContainerSnapshot
from .base import Trigger


class ContainerStoppedTrigger(Trigger):
    incident_type = "CONTAINER_STOPPED"

    STOPPED_STATUSES = {"created", "dead", "exited", "paused", "removing", "stopped"}

    def evaluate(self, snapshot: ContainerSnapshot) -> bool:
        if not snapshot.exists:
            return False
        if snapshot.status == "restarting" or snapshot.raw.get("Restarting"):
            return False
        # Docker may publish exit 137 before OOMKilled. SIGKILL alone does not
        # establish an OOM cause or justify an automatic generic restart.
        if not snapshot.running and snapshot.exit_code == 137 and not snapshot.oom_killed:
            return False
        return not snapshot.running or snapshot.status in self.STOPPED_STATUSES

    def build_metadata(self, snapshot: ContainerSnapshot) -> dict:
        return {
            "reason": f"{snapshot.name} is not running",
            "observed_state": snapshot.status,
            "expected_state": "running",
            "status": snapshot.status,
            "exit_code": snapshot.exit_code,
            "health": snapshot.health,
            "restart_count": snapshot.restart_count,
        }

    def trace(self, snapshot: ContainerSnapshot) -> dict:
        result = self.evaluate(snapshot)
        if not snapshot.exists:
            reason = "container missing"
        elif snapshot.status == "restarting" or snapshot.raw.get("Restarting"):
            reason = "container is restarting"
        elif snapshot.running:
            reason = "container is running"
        elif snapshot.exit_code == 137 and not snapshot.oom_killed:
            reason = "exit_code=137 with oom_killed=false: SIGKILL cause unconfirmed; automatic restart withheld"
        else:
            reason = "container is not running"
        return {
            "incident_type": self.incident_type,
            "running": snapshot.running,
            "status": snapshot.status,
            "result": result,
            "reason": reason,
        }
