from __future__ import annotations

from datetime import datetime
from typing import Any

from ..audit_reader import find_incident_after


def seconds_between(start: str | None, end: str | None) -> float | None:
    if start is None or end is None:
        return None
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def wait_for_audit_detection(
    incident_type: str,
    resource: str,
    since: str,
    return_record: bool = False,
) -> str | dict[str, Any] | None:
    incident = find_incident_after(incident_type, resource, since)
    if incident is None:
        return None
    if return_record:
        return incident
    return (incident.get("timestamps") or {}).get("updated_at")

