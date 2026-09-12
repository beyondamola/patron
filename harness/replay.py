"""Recorded execution adapters. This module never constructs a live Docker adapter."""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from .audit import AuditLogger
from .capture import read_capture, sanitized
from .capture_validation import validate_capture
from .collector import ContainerSnapshot
from .config import DetectorConfig
from .control import ControlRequest, IncidentControl
from .incident import IncidentRegistry
from .planner import RulePlanner
from .runtime import PatronRuntime
from .storage import atomic_json
from .verifier import VerificationResult


class ReplayMismatch(ValueError):
    pass


def first_difference(actual, expected, path="payload"):
    if isinstance(actual, dict) and isinstance(expected, dict):
        for key in sorted(set(actual) | set(expected)):
            if key not in actual or key not in expected:
                return f"{path}.{key}: missing field"
            if not equivalent(actual[key], expected[key], key):
                return first_difference(actual[key], expected[key], f"{path}.{key}")
    if isinstance(actual, list) and isinstance(expected, list):
        for index, (left, right) in enumerate(zip(actual, expected)):
            if not equivalent(left, right):
                return first_difference(left, right, f"{path}[{index}]")
    return f"{path}: computed={actual!r}, recorded={expected!r}"


def equivalent(actual, expected, key=None):
    if key in {"coverage_seconds", "recovery_coverage_seconds"}:
        if type(actual) in (int, float) and type(expected) in (int, float):
            return math.isclose(actual, expected, rel_tol=0, abs_tol=0.000001)
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(equivalent(actual[k], expected[k], k) for k in actual)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(equivalent(a, b) for a, b in zip(actual, expected))
    return actual == expected


def semantic(value):
    """Exclude storage locations and wall-time measurements, not behavioral state."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in {"created_at", "updated_at", "timestamps", "timestamp", "state_path", "audit_path", "metrics"}:
                continue
            if key == "resolved_at":
                result[key] = sorted(item)
            else:
                result[key] = semantic(item)
        return result
    if isinstance(value, list):
        return [semantic(item) for item in value]
    return value


class RecordedClock:
    def __init__(self, stream):
        self.stream = stream
        self.record = stream.records[0]

    def advance(self, record):
        self.record = record

    def monotonic(self):
        return self.record["monotonic_offset"]

    def utc_now(self):
        upcoming = self.stream.peek()
        if upcoming and upcoming["event"] == "transition":
            return upcoming["payload"]["incident"]["updated_at"]
        return self.record["utc_time"]

    def sleep(self, seconds):
        raise ReplayMismatch("unexpected runtime sleep; replay advances recorded observations")


class EventStream:
    def __init__(self, records):
        self.records = records
        self.index = 1
        self.clock = RecordedClock(self)

    def peek(self):
        return self.records[self.index] if self.index < len(self.records) else None

    def expected(self, event):
        record = self.peek()
        if record is None or record["event"] != event:
            raise ReplayMismatch(f"expected {event}, recorded {record['event'] if record else 'end of file'} at sequence {self.index}")
        return record

    def consume(self, event, payload=None):
        record = self.expected(event)
        if payload is not None and not equivalent(semantic(sanitized(payload)), semantic(record["payload"])):
            raise ReplayMismatch(f"{event} payload differs at sequence {self.index}: {first_difference(semantic(sanitized(payload)), semantic(record['payload']))}")
        self.clock.advance(record)
        self.index += 1
        return record


class RecordedCollector:
    def __init__(self, stream):
        self.stream = stream

    def collect(self):
        record = self.stream.expected("observation")
        self.stream.clock.advance(record)
        snapshot = record["payload"]["snapshot"]
        return ContainerSnapshot(**snapshot, raw={"Restarting": snapshot["status"] == "restarting"})


class RecordedPlanner:
    def __init__(self, stream):
        self.stream = stream

    def plan(self, context):
        plan = RulePlanner().plan(context)
        self.stream.clock.advance(self.stream.expected("plan"))
        return plan


class RecordedExecutor:
    def __init__(self, stream):
        self.stream = stream

    def execute(self, plan, context):
        record = self.stream.expected("execution")
        self.stream.clock.advance(record)
        return deepcopy(record["payload"]["result"])


class ReplaySink:
    def __init__(self, stream):
        self.stream = stream

    def emit(self, event, payload, **references):
        record = self.stream.consume(event, payload)
        for key in ("observation_id", "incident_id"):
            if references.get(key) != record.get(key):
                raise ReplayMismatch(f"{event} {key} differs at sequence {record['sequence']}")
        return record["sequence"]

    def observe(self, snapshot, **kwargs):
        return self.stream.consume("observation")["sequence"]

    def close(self):
        pass


class RecordedVerifier:
    def __init__(self, stream):
        self.stream = stream

    def __call__(self, name, incident_type, decision, **kwargs):
        while self.stream.peek() and self.stream.peek()["event"] == "verification_observation":
            self.stream.consume("verification_observation")
        record = self.stream.expected("verification")
        payload = record["payload"]
        if payload["decision"] != decision or payload["incident_type"] != incident_type:
            raise ReplayMismatch("verification input differs")
        if payload.get("incident_status") != kwargs.get("incident_status"):
            raise ReplayMismatch("verification incident state differs")
        self.stream.clock.advance(record)
        return VerificationResult(**payload["result"])


def replay_capture(path: str | Path) -> dict:
    records = read_capture(path)
    validation = validate_capture(records)
    stream = EventStream(records)
    header = records[0]["payload"]
    settings = header["runtime_settings"]
    if settings.get("mode") not in {"watch", "cycles"}:
        raise ReplayMismatch("capture lacks runtime mode needed to reproduce shutdown persistence; record a new capture")
    cycles = []
    with TemporaryDirectory(prefix="patron-replay-") as directory:
        root = Path(directory)
        state = deepcopy(header["initial_state"])
        state["audit_path"] = str(root / "audit.jsonl")
        for event in state["outbox"].values():
            event["state_path"] = str(root / "state.json")
        atomic_json(root / "state.json", state)

        def incident_id():
            return stream.expected("transition")["payload"]["incident"]["incident_id"]

        registry = IncidentRegistry(root / "state.json", cooldown_seconds=settings["cooldown_seconds"],
                                    clock=stream.clock, id_factory=incident_id)
        runtime = PatronRuntime(container_name=settings["target"], dry_run=settings["dry_run"],
            config=DetectorConfig(**header["config"]), registry=registry,
            audit_logger=AuditLogger(root / "audit.jsonl"), collector=RecordedCollector(stream),
            planner=RecordedPlanner(stream), executor=RecordedExecutor(stream), verifier=RecordedVerifier(stream))
        runtime.capture = ReplaySink(stream)
        while stream.peek() and stream.peek()["event"] != "run_end":
            stream.clock.advance(stream.expected("cycle_start"))
            # Materialize recorded requests only in the isolated inbox. The runtime
            # remains responsible for validation, revision checks, and application.
            for record in records[stream.index + 1:]:
                if record["event"] != "control":
                    break
                if record["payload"]["phase"] == "requested":
                    request = ControlRequest(**record["payload"]["request"])
                    IncidentControl(registry, runtime.audit_logger).submit(request)
            result = runtime.process_once()
            cycles.append({"triggered": result.get("triggered"),
                "incident_type": (result.get("incident") or {}).get("incident_type"),
                "final_status": (result.get("incident") or {}).get("status"),
                "attempts": (result.get("incident") or {}).get("attempts"),
                "error": result.get("error")})
        if settings["mode"] == "watch":
            registry.persist()
        runtime.finish_capture()
        if stream.index != len(records):
            raise ReplayMismatch("unconsumed capture events")
    from .replay_metrics import exact_metrics
    return {"schema_version": 1, "mode": "exact", "matched": True,
            "agreement": exact_metrics(records),
            "comparison_scope": "decisions and lifecycle state; timestamps, storage paths and latency excluded",
            **validation, "cycle_results": cycles,
            "recorded_metrics": [record["payload"]["result"]["audit"]["metrics"] for record in records
                if record["event"] == "cycle_end" and "audit" in record["payload"]["result"]]}
