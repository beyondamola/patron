from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .storage import StateConflict, StateLock, atomic_json, sync_directory
from .clock import Clock, SystemClock


OPEN = "OPEN"
RUNNING = "RUNNING"
RESOLVED = "RESOLVED"
ESCALATED = "ESCALATED"
FAILED = "FAILED"
FINAL_STATUSES = {RESOLVED, ESCALATED, FAILED}
STATE_SCHEMA_VERSION = 1


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
    container_id: str | None = None
    predecessor_id: str | None = None
    acknowledgment: dict[str, Any] | None = None
    rearmed: bool = False

    @classmethod
    def open(
        cls,
        resource: str,
        resource_type: str,
        incident_type: str,
        trigger_reason: str,
        *,
        clock: Clock | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> "Incident":
        now = clock.utc_now() if clock else utc_now()
        return cls(
            incident_id=id_factory() if id_factory else str(uuid4()),
            resource=resource,
            resource_type=resource_type,
            incident_type=incident_type,
            status=OPEN,
            attempts=0,
            created_at=now,
            updated_at=now,
            trigger_reason=trigger_reason,
        )

    def touch(self, clock: Clock | None = None) -> None:
        self.updated_at = clock.utc_now() if clock else utc_now()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Incident":
        payload = dict(payload)
        payload.setdefault("incident_type", "UNKNOWN")
        incident = cls(**payload)
        if incident.status not in FINAL_STATUSES | {OPEN, RUNNING}:
            raise ValueError(f"Unknown incident status: {incident.status}")
        if type(incident.attempts) is not int or incident.attempts < 0:
            raise ValueError("Incident attempts must be a nonnegative integer")
        for field in (incident.incident_id, incident.resource, incident.resource_type, incident.incident_type):
            if not isinstance(field, str) or not field:
                raise ValueError("Incident identity fields must be nonempty strings")
        for value in (incident.created_at, incident.updated_at):
            if parse_time(value).tzinfo is None:
                raise ValueError("Incident timestamps must include a timezone")
        if type(incident.rearmed) is not bool:
            raise ValueError("Incident rearmed flag must be boolean")
        for value in (incident.container_id, incident.predecessor_id):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError("Optional incident identities must be nonempty strings")
        if incident.acknowledgment is not None:
            if not isinstance(incident.acknowledgment, dict) or any(
                    not isinstance(incident.acknowledgment.get(key), str) or not incident.acknowledgment[key]
                    for key in ("actor", "reason", "timestamp")):
                raise ValueError("Malformed incident acknowledgment")
            if parse_time(incident.acknowledgment["timestamp"]).tzinfo is None:
                raise ValueError("Acknowledgment timestamp must include a timezone")
        return incident


class IncidentRegistry:
    def __init__(
        self,
        state_path: Path | str | None = None,
        cooldown_seconds: int = 60,
        *,
        clock: Clock | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.clock = clock or SystemClock()
        self.id_factory = id_factory
        self.state_path = Path(state_path or os.environ.get("PATRON_STATE_PATH", "logs/incident_state.json")).resolve()
        self.lock = StateLock(self.state_path)
        self.revision = 0
        self._legacy = False
        self.cooldown_seconds = cooldown_seconds
        self.incidents: dict[str, Incident] = {}
        self.resolved_at: dict[str, str] = {}
        self.control_results: dict[str, Any] = {}
        self.outbox: dict[str, Any] = {}
        self.audit_path: str | None = None
        self.observed_generations: dict[str, str] = {}
        self.resolved_generations: dict[str, str | None] = {}
        self.resolved_incident_types: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if not self.state_path.exists():
            return
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Incident state must be a JSON object")
        version = payload.get("schema_version", 0)
        if type(version) is not int or version not in (0, STATE_SCHEMA_VERSION):
            raise ValueError(f"Unsupported incident state schema: {version}")
        revision = payload.get("revision", 0)
        if type(revision) is not int or revision < 0:
            raise ValueError("State revision must be a nonnegative integer")
        if not isinstance(payload.get("incidents"), dict) or not isinstance(payload.get("resolved_at"), dict):
            raise ValueError("Incident state requires incidents and resolved_at objects")
        incidents = {
            key: Incident.from_dict(value)
            for key, value in payload.get("incidents", {}).items()
        }
        if any(key != incident.resource for key, incident in incidents.items()):
            raise ValueError("Incident state resource keys do not match incident identities")
        for value in payload["resolved_at"].values():
            if parse_time(value).tzinfo is None:
                raise ValueError("Cooldown timestamps must include a timezone")
        self.incidents = incidents
        self.resolved_at = payload["resolved_at"]
        self.revision = revision
        self._legacy = version == 0
        for field in ("control_results", "outbox"):
            value = payload.get(field, {})
            if not isinstance(value, dict):
                raise ValueError(f"State {field} must be an object")
            setattr(self, field, value)
        self.audit_path = payload.get("audit_path")
        if self.audit_path is not None and not isinstance(self.audit_path, str):
            raise ValueError("State audit_path must be a string")
        for field in ("observed_generations", "resolved_generations", "resolved_incident_types"):
            value = payload.get(field, {})
            if not isinstance(value, dict) or any(not isinstance(key, str) or (item is not None and not isinstance(item, str)) for key, item in value.items()):
                raise ValueError(f"Invalid {field}")
            setattr(self, field, value)
        from .control import validate_control_envelope
        validate_control_envelope(self.control_results, self.outbox, self.state_path)

    def check_revision(self) -> None:
        if self.state_path.exists():
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or type(payload.get("schema_version", 0)) is not int or payload.get("schema_version", 0) not in (0, STATE_SCHEMA_VERSION):
                raise ValueError("Invalid or unsupported incident state schema")
            if payload.get("revision", 0) != self.revision:
                raise StateConflict("Incident state changed; reload before continuing")
        elif self.revision:
            raise StateConflict("Incident state disappeared; refusing to recreate it silently")

    def persist(self) -> None:
        with self.lock.acquire():
            self.check_revision()
            self._persist_owned()

    def _persist_owned(self) -> None:
        if self._legacy:
            backup = self.state_path.with_name(self.state_path.name + ".v0.bak")
            original = self.state_path.read_bytes()
            if backup.exists():
                if backup.read_bytes() != original:
                    raise StateConflict(f"Migration backup already exists with different contents: {backup}")
            else:
                with backup.open("xb") as stream:
                    stream.write(original)
                    stream.flush()
                    os.fsync(stream.fileno())
                sync_directory(backup.parent)
        payload = self.export_state()
        payload["revision"] = self.revision + 1
        atomic_json(self.state_path, payload)
        self.revision += 1
        self._legacy = False

    def export_state(self) -> dict:
        """Return a detached envelope without changing its revision or storage."""
        payload = {
            "schema_version": STATE_SCHEMA_VERSION,
            "revision": self.revision,
            "incidents": {
                key: incident.to_dict()
                for key, incident in self.incidents.items()
            },
            "resolved_at": self.resolved_at,
            "control_results": self.control_results,
            "outbox": self.outbox,
            "audit_path": self.audit_path,
            "observed_generations": self.observed_generations,
            "resolved_generations": self.resolved_generations,
            "resolved_incident_types": self.resolved_incident_types,
        }
        return json.loads(json.dumps(payload))

    def matches_generation(self, incident: Incident, container_id: str | None = None) -> bool:
        observed = container_id or self.observed_generations.get(incident.resource)
        return not (incident.container_id and observed and incident.container_id != observed)

    def observe_generation(self, resource: str, container_id: str | None) -> bool:
        if container_id and self.observed_generations.get(resource) != container_id:
            self.observed_generations[resource] = container_id
            return True
        return False

    def active_for(self, resource: str) -> Incident | None:
        incident = self.incidents.get(resource)
        if incident and incident.status not in FINAL_STATUSES and self.matches_generation(incident):
            return incident
        return None

    def in_cooldown(self, resource: str, container_id: str | None = None, incident_type: str | None = None) -> bool:
        previous_type = self.resolved_incident_types.get(resource)
        if incident_type and previous_type and incident_type != previous_type:
            return False
        observed = container_id or self.observed_generations.get(resource)
        resolved_id = self.resolved_generations.get(resource)
        if observed and resolved_id and observed != resolved_id:
            return False
        resolved = self.resolved_at.get(resource)
        if not resolved:
            return False
        elapsed = (parse_time(self.clock.utc_now()) - parse_time(resolved)).total_seconds()
        return elapsed < self.cooldown_seconds

    def get_or_open(
        self,
        resource: str,
        resource_type: str,
        incident_type: str,
        trigger_reason: str,
        container_id: str | None = None,
    ) -> tuple[Incident | None, bool]:
        previous = self.incidents.get(resource)
        if previous and not self.matches_generation(previous, container_id):
            previous = None
        if previous and previous.status in {ESCALATED, FAILED} and not previous.rearmed:
            return None, False
        active = self.active_for(resource)
        if active and not self.matches_generation(active, container_id):
            active = None
        if active:
            active.incident_type = incident_type
            active.trigger_reason = trigger_reason
            return active, False
        if self.in_cooldown(resource, container_id, incident_type):
            return None, False
        incident = Incident.open(resource, resource_type, incident_type, trigger_reason,
                                 clock=self.clock, id_factory=self.id_factory)
        incident.container_id = container_id
        if previous and previous.rearmed:
            incident.predecessor_id = previous.incident_id
        self.incidents[resource] = incident
        return incident, True

    def mark_resolved(self, incident: Incident) -> None:
        incident.status = RESOLVED
        incident.touch(self.clock)
        self.resolved_at[incident.resource] = incident.updated_at
        self.resolved_generations[incident.resource] = incident.container_id
        self.resolved_incident_types[incident.resource] = incident.incident_type
        self.incidents.pop(incident.resource, None)

    def mark_final(self, incident: Incident, status: str) -> None:
        incident.status = status
        incident.touch(self.clock)
        if status == ESCALATED:
            self.resolved_at[incident.resource] = incident.updated_at
            self.resolved_generations[incident.resource] = incident.container_id
        self.incidents[incident.resource] = incident
