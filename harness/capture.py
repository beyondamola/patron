"""Versioned, bounded normalized capture primitives. Never serialize raw inspect."""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from uuid import uuid4

from .clock import Clock, SystemClock
from .collector import ContainerSnapshot, parse_timestamp
from .config import DetectorConfig


SCHEMA_VERSION = 1
REDACTION_VERSION = 1
EVENTS = {"run_start", "observation", "context", "plan", "policy", "action_requested",
          "execution", "verification_observation", "verification", "transition", "control",
          "cycle_end", "run_end"}
SNAPSHOT_FIELDS = (
    "name", "exists", "running", "status", "exit_code", "health", "restart_count",
    "container_id", "has_healthcheck", "restart_policy", "oom_killed",
    "memory_limit_bytes", "memory_usage_bytes", "cpu_percent", "disk_usage_percent",
    "recent_logs", "error_patterns", "ports", "network_mode", "dependency_status",
    "observed_monotonic", "started_at", "cpu_quota", "cpu_period", "nano_cpus", "probe_errors",
)


def redact_text(value: str) -> str:
    value = re.sub(r"(?i)(bearer\s+)[^\s\",]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)((?:password|token|secret|api_key)[\s\"':=]+)[^\s\",]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})", "[REDACTED]", value)
    return re.sub(r"(https?://)[^/\s:@]+:[^/\s@]+@", r"\1[REDACTED]@", value)


def sanitized(value, depth=0):
    if depth > 12:
        raise ValueError("capture payload nesting exceeds limit")
    if isinstance(value, str):
        return redact_text(value)[:4000]
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        if len(value) > 1000:
            raise ValueError("capture list exceeds limit")
        return [sanitized(item, depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 1000 or any(not isinstance(key, str) for key in value):
            raise ValueError("invalid capture mapping")
        return {key: ("[REDACTED]" if re.search(r"(?i)password|secret|token|api_key|authorization", key)
                      else sanitized(item, depth + 1)) for key, item in value.items()
                if key not in {"raw", "env", "Env", "environment"}}
    raise ValueError(f"unsupported capture value: {type(value).__name__}")


def normalized_snapshot(snapshot: ContainerSnapshot, origin: float) -> dict:
    packet = {key: getattr(snapshot, key) for key in SNAPSHOT_FIELDS}
    packet["recent_logs"] = [redact_text(line)[:1000] for line in (snapshot.recent_logs or [])[-20:]]
    if packet["observed_monotonic"] is not None:
        packet["observed_monotonic"] -= origin
    return sanitized(packet)


class CaptureWriter:
    def __init__(self, path: str | Path, *, config: DetectorConfig, initial_state: dict,
                 clock: Clock | None = None, run_id: str | None = None) -> None:
        self.clock = clock or SystemClock()
        self.origin = self.clock.monotonic()
        self.run_id = run_id or str(uuid4())
        self.sequence = 0
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation avoids overwriting an earlier run or following a final symlink.
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.handle = os.fdopen(descriptor, "w", encoding="utf-8")
        try:
            self.emit("run_start", {"config": config.to_dict(), "config_fingerprint": config.fingerprint,
                      "initial_state": initial_state, "collector_version": 1,
                      "redaction_version": REDACTION_VERSION})
        except BaseException:
            self.handle.close()
            raise

    def emit(self, event: str, payload: dict, *, observation_id: int | None = None,
             incident_id: str | None = None) -> int:
        if event not in EVENTS or not isinstance(payload, dict):
            raise ValueError("unsupported capture event or payload")
        record = {"schema_version": SCHEMA_VERSION, "run_id": self.run_id,
                  "sequence": self.sequence, "event": event, "utc_time": self.clock.utc_now(),
                  "monotonic_offset": self.clock.monotonic() - self.origin,
                  "observation_id": observation_id, "incident_id": incident_id,
                  "payload": sanitized(payload)}
        encoded = json.dumps(record, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 1_000_000:
            raise ValueError("capture record exceeds 1MB")
        self.handle.write(encoded + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.sequence += 1
        return record["sequence"]

    def observe(self, snapshot: ContainerSnapshot, *, verification: bool = False,
                observation_id: int | None = None, incident_id: str | None = None) -> int:
        return self.emit("verification_observation" if verification else "observation",
                         {"snapshot": normalized_snapshot(snapshot, self.origin)},
                         observation_id=observation_id, incident_id=incident_id)

    def close(self) -> None:
        self.handle.close()


def read_capture(path: str | Path) -> list[dict]:
    records = []
    with Path(path).open("rb") as stream:
        while True:
            line = stream.readline(1_000_002)
            if not line:
                break
            number = len(records)
            if len(line) > 1_000_001:
                raise ValueError("capture record exceeds 1MB")
            if not line.endswith(b"\n"):
                raise ValueError("incomplete final capture write")
            record = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite capture number")))
            if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("unsupported capture schema; incident audit lacks replay observations")
            if type(record.get("sequence")) is not int or record["sequence"] != number:
                raise ValueError("missing or out-of-order capture sequence")
            offset = record.get("monotonic_offset")
            if type(offset) not in (int, float) or not math.isfinite(offset) or offset < 0:
                raise ValueError("invalid capture monotonic offset")
            if not isinstance(record.get("run_id"), str) or not record["run_id"]:
                raise ValueError("missing capture run ID")
            if parse_timestamp(record.get("utc_time")) is None:
                raise ValueError("invalid capture UTC timestamp")
            if record.get("event") not in EVENTS or not isinstance(record.get("payload"), dict):
                raise ValueError("invalid capture event")
            if number and record["event"] == "run_start":
                raise ValueError("duplicate capture run_start")
            if records and records[-1]["event"] == "run_end":
                raise ValueError("capture events after run_end")
            if records and (record["run_id"] != records[0]["run_id"] or offset < records[-1]["monotonic_offset"]):
                raise ValueError("capture run identity or clock discontinuity")
            records.append(record)
    if not records or records[0]["event"] != "run_start" or not isinstance(records[0]["payload"].get("initial_state"), dict):
        raise ValueError("missing capture initial state")
    if records[-1]["event"] != "run_end":
        raise ValueError("incomplete capture: missing run_end")
    config = DetectorConfig(**records[0]["payload"].get("config", {}))
    if records[0]["payload"].get("config_fingerprint") != config.fingerprint:
        raise ValueError("capture configuration fingerprint mismatch")
    return records
