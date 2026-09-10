"""Operator requests; no Docker operations or planner access."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from datetime import datetime
from uuid import UUID, uuid4

from .audit import AuditLogger
from .incident import ESCALATED, FAILED, IncidentRegistry, utc_now
from .storage import StateConflict, StateLock, atomic_json, sync_directory


@dataclass(frozen=True)
class ControlRequest:
    request_id: str
    incident_id: str
    expected_revision: int
    operation: str
    reason: str
    actor: str
    created_at: str

    def validate(self):
        if str(UUID(self.request_id)) != self.request_id:
            raise ValueError("request_id must be a canonical UUID")
        if self.operation not in {"acknowledge", "rearm"}:
            raise ValueError("Unknown operator action")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError("Expected revision must be a nonnegative integer")
        for value in (self.incident_id, self.reason, self.actor):
            if not isinstance(value, str) or not value.strip() or len(value) > 2000:
                raise ValueError("Incident ID, reason, and actor must be nonempty bounded strings")
        if datetime.fromisoformat(self.created_at).tzinfo is None:
            raise ValueError("Request timestamp must include a timezone")


def audit_records(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.endswith("\n"):
                break
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Corrupt complete audit record in {path}") from exc
            if isinstance(record, dict):
                yield record


class IncidentControl:
    def __init__(self, registry: IncidentRegistry, audit: AuditLogger | None = None):
        self.registry = registry
        self.audit = audit or AuditLogger(registry.audit_path or "logs/incidents.jsonl")
        self.inbox = registry.state_path.with_name(registry.state_path.name + ".requests")

    def incidents(self) -> dict:
        records = {}
        for record in audit_records(self.audit.path):
            if record.get("state_path") and record["state_path"] != str(self.registry.state_path):
                continue
            if not record.get("state_path") and self.registry.state_path != Path("logs/incident_state.json").resolve():
                resource = (record.get("context_summary") or {}).get("resource")
                if resource not in set(self.registry.incidents) | set(self.registry.resolved_at):
                    continue
            incident = record.get("incident")
            if not incident and record.get("incident_id") and record.get("final_status") and record.get("context_summary"):
                incident = {
                    "incident_id": record["incident_id"], "status": record["final_status"],
                    "resource": record["context_summary"].get("resource"),
                    "incident_type": record.get("incident_type"), "attempts": record.get("retry_count"),
                    **(record.get("timestamps") or {}), "container_id": None,
                }
            if incident and incident.get("incident_id"):
                records[incident["incident_id"]] = dict(incident)
        for incident in self.registry.incidents.values():
            records[incident.incident_id] = incident.to_dict()
        for incident in records.values():
            current = self.registry.incidents.get(incident.get("resource"))
            incident["suppressed"] = bool(current and current.incident_id == incident["incident_id"]
                and current.status in {ESCALATED, FAILED} and not current.rearmed)
            incident["evidence_path"] = str(self.audit.path.resolve())
        return records

    def request_result(self, request_id: str):
        UUID(request_id)
        entry = self.registry.control_results.get(request_id)
        if entry:
            result = dict(entry["result"])
            if request_id in self.registry.outbox:
                result["status"] = "PENDING_AUDIT"
            return result
        for record in audit_records(self.audit.path):
            if record.get("event_id") == request_id and record.get("state_path") == str(self.registry.state_path):
                return record.get("result")
        return None

    def submit(self, request: ControlRequest) -> None:
        request.validate()
        self.inbox.mkdir(parents=True, exist_ok=True)
        with StateLock(self.inbox / "queue").acquire():
            path = self.inbox / f"{request.request_id}.json"
            if path.exists():
                if json.loads(path.read_text()) != asdict(request):
                    raise StateConflict("Request ID already has different contents")
            else:
                atomic_json(path, asdict(request))

    def _event(self, request, result, incident):
        return {"schema_version": 1, "event": "operator_control", "event_id": request.request_id,
                "state_path": str(self.registry.state_path), "timestamp": utc_now(),
                "request": asdict(request), "result": result, "incident": incident}

    def apply(self, request: ControlRequest, dry_run=False):
        with self.registry.lock.acquire():
            self.registry.check_revision()
            try:
                return self._apply_owned(request, dry_run)
            except Exception:
                self.registry.load()
                raise

    def _apply_owned(self, request: ControlRequest, dry_run=False):
        request.validate()
        existing = self.request_result(request.request_id)
        if existing:
            if any(existing.get(key) != getattr(request, key) for key in ("operation", "incident_id", "reason", "actor")):
                raise StateConflict("Request ID already used for another operation")
            return existing
        result = {"request_id": request.request_id, "incident_id": request.incident_id,
                  "operation": request.operation, "reason": request.reason, "actor": request.actor, "status": "APPLIED"}
        incident = self.incidents().get(request.incident_id)
        error = None
        if request.expected_revision != self.registry.revision:
            error = "State revision changed; submit a new request after inspecting current state"
        elif not incident:
            error = "Incident not found"
        elif request.operation == "rearm":
            current = self.registry.incidents.get(incident["resource"])
            if not current or current.incident_id != request.incident_id or current.status not in {ESCALATED, FAILED} or current.rearmed:
                error = "Only the currently suppressed ESCALATED or FAILED incident can be rearmed"
        if error:
            result.update(status="REJECTED", error=error)
        elif not dry_run:
            current = self.registry.incidents.get(incident["resource"])
            if request.operation == "acknowledge":
                metadata = {"actor": request.actor, "reason": request.reason, "timestamp": utc_now()}
                incident["acknowledgment"] = metadata
                if current and current.incident_id == request.incident_id:
                    current.acknowledgment = metadata
            else:
                current.rearmed = True
                self.registry.resolved_at.pop(current.resource, None)
                incident = current.to_dict()
        if dry_run:
            return {**result, "status": "DRY_RUN" if not error else "REJECTED"}
        event = self._event(request, result, incident)
        self.registry.control_results[request.request_id] = {"request": asdict(request), "result": result}
        self.registry.outbox[request.request_id] = event
        self.registry.audit_path = str(self.audit.path.resolve())
        self.registry.persist()
        self.flush()
        return result

    def flush(self):
        for request_id, event in list(self.registry.outbox.items()):
            already_logged = any(record.get("event_id") == request_id and record.get("state_path") == str(self.registry.state_path) for record in audit_records(self.audit.path))
            if not already_logged:
                self.audit.log(event)
            del self.registry.outbox[request_id]
            self.registry.persist()
        # Durable audit events retain older results for idempotent request lookup.
        while len(self.registry.control_results) > 256:
            oldest = next(iter(self.registry.control_results))
            if oldest in self.registry.outbox:
                break
            del self.registry.control_results[oldest]
        self.registry.persist()

    def process_pending(self):
        self.flush() if self.registry.outbox else None
        if not self.inbox.exists():
            return
        for path in sorted(self.inbox.glob("*.json"))[:32]:
            if path.is_symlink() or path.stat().st_size > 16000:
                raise ValueError(f"Invalid control request file: {path}")
            request = ControlRequest(**json.loads(path.read_text()))
            if path.stem != request.request_id:
                raise ValueError("Control request filename does not match its ID")
            self.apply(request)
            path.unlink()
            sync_directory(self.inbox)


def execute_request(registry, operation, incident_id, reason, actor, request_id=None, dry_run=False, timeout=5.0):
    control = IncidentControl(registry)
    request = ControlRequest(request_id or str(uuid4()), incident_id, registry.revision,
                             operation, reason, actor, utc_now())
    request.validate()
    existing = control.request_result(request.request_id)
    if existing:
        if any(existing.get(key) != value for key, value in (("operation", operation), ("incident_id", incident_id), ("reason", reason), ("actor", actor))):
            raise StateConflict("Request ID already used for another operation")
        if existing.get("status") == "PENDING_AUDIT" and not dry_run:
            try:
                with registry.lock.acquire():
                    registry.load()
                    control.flush()
            except StateConflict:
                return existing
            return control.request_result(request.request_id)
        return existing
    if dry_run:
        return control.apply(request, dry_run=True)
    control.submit(request)
    deadline = time.monotonic() + timeout
    while True:
        try:
            with registry.lock.acquire():
                registry.load()
                control.process_pending()
        except StateConflict:
            pass  # A live runtime applies the same request at its next cycle boundary.
        registry.load()
        result = control.request_result(request.request_id)
        if result and result["status"] != "PENDING_AUDIT":
            return result
        if time.monotonic() >= deadline:
            return result or {"request_id": request.request_id, "status": "PENDING"}
        time.sleep(0.1)
