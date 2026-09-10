from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def read_incidents(path: Path | str = "logs/incidents.jsonl") -> list[dict[str, Any]]:
    audit_path = Path(path)
    if not audit_path.exists():
        return []
    incidents = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                incidents.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # A running writer may have an incomplete final line.
    return incidents


def find_incident_after(
    incident_type: str,
    resource: str,
    since: str,
    path: Path | str = "logs/incidents.jsonl",
) -> dict[str, Any] | None:
    since_dt = parse_time(since)
    for incident in reversed(read_incidents(path)):
        if incident.get("incident_type") != incident_type:
            continue
        summary = incident.get("context_summary") or {}
        if summary.get("resource") != resource:
            continue
        updated = parse_time((incident.get("timestamps") or {}).get("updated_at"))
        if not updated or (since_dt and updated < since_dt):
            continue
        return incident
    return None
