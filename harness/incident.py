from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


OPEN = "OPEN"
RUNNING = "RUNNING"
RESOLVED = "RESOLVED"
ESCALATED = "ESCALATED"
FAILED = "FAILED"
FINAL_STATUSES = {RESOLVED, ESCALATED, FAILED}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass
class Incident:
    incident_id: str
    resource: str
    resource_type: str
    incident_type: str
    status: str
    attempts: int
    created_at: str
    updated_at: str
    last_action: str | None = None
    verification_state: dict[str, Any] | None = None
    trigger_reason: str | None = None

    @classmethod
    def open(
        cls,
        resource: str,
        resource_type: str,
        incident_type: str,
        trigger_reason: str,
    ) -> "Incident":
        now = utc_now()
        return cls(
            incident_id=str(uuid4()),
            resource=resource,
            resource_type=resource_type,
            incident_type=incident_type,
            status=OPEN,
            attempts=0,
            created_at=now,
            updated_at=now,
            trigger_reason=trigger_reason,
        )

    def touch(self) -> None:
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Incident":
        payload.setdefault("incident_type", "UNKNOWN")
        return cls(**payload)


class IncidentRegistry:
    def __init__(
        self,
        state_path: Path | str = "logs/incident_state.json",
        cooldown_seconds: int = 60,
    ) -> None:
        self.state_path = Path(os.environ.get("PATRON_STATE_PATH", state_path))
        self.cooldown_seconds = cooldown_seconds
        self.incidents: dict[str, Incident] = {}
        self.resolved_at: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if not self.state_path.exists():
            return
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.incidents = {
            key: Incident.from_dict(value)
            for key, value in payload.get("incidents", {}).items()
        }
        self.resolved_at = payload.get("resolved_at", {})

    def persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "incidents": {
                key: incident.to_dict()
                for key, incident in self.incidents.items()
            },
            "resolved_at": self.resolved_at,
        }
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.state_path)

    def active_for(self, resource: str) -> Incident | None:
        incident = self.incidents.get(resource)
        if incident and incident.status not in FINAL_STATUSES:
            return incident
        return None

    def in_cooldown(self, resource: str) -> bool:
        resolved = self.resolved_at.get(resource)
        if not resolved:
            return False
        elapsed = (datetime.now(timezone.utc) - parse_time(resolved)).total_seconds()
        return elapsed < self.cooldown_seconds

    def get_or_open(
        self,
        resource: str,
        resource_type: str,
        incident_type: str,
        trigger_reason: str,
    ) -> tuple[Incident | None, bool]:
        previous = self.incidents.get(resource)
        if previous and previous.status in {ESCALATED, FAILED}:
            return None, False
        active = self.active_for(resource)
        if active:
            active.incident_type = incident_type
            active.trigger_reason = trigger_reason
            return active, False
        if self.in_cooldown(resource):
            return None, False
        incident = Incident.open(resource, resource_type, incident_type, trigger_reason)
        self.incidents[resource] = incident
        return incident, True

    def mark_resolved(self, incident: Incident) -> None:
        incident.status = RESOLVED
        incident.touch()
        self.resolved_at[incident.resource] = incident.updated_at
        self.incidents.pop(incident.resource, None)

    def mark_final(self, incident: Incident, status: str) -> None:
        incident.status = status
        incident.touch()
        if status == ESCALATED:
            self.resolved_at[incident.resource] = incident.updated_at
        self.incidents[incident.resource] = incident
