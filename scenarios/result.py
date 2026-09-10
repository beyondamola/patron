from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


PASSED = "PASSED"
FAILED = "FAILED"
TIMED_OUT = "TIMED_OUT"
SETUP_FAILED = "SETUP_FAILED"
INJECTION_FAILED = "INJECTION_FAILED"
CLEANUP_FAILED = "CLEANUP_FAILED"
RESULT_STATES = {PASSED, FAILED, TIMED_OUT, SETUP_FAILED, INJECTION_FAILED, CLEANUP_FAILED}


@dataclass
class ScenarioResult:
    scenario_id: str
    scenario_name: str
    target: str
    status: str
    failure_injected: bool
    failure_observed: bool
    recovery_observed: bool
    injected_at: str | None
    detected_at: str | None
    recovered_at: str | None
    detection_latency_seconds: float | None
    recovery_latency_seconds: float | None
    final_container_state: str | None
    error: str | None = None
    patron_incident_id: str | None = None
    expected_incident_type: str | None = None
    observed_incident_type: str | None = None
    expected_final_status: str | None = None
    observed_final_status: str | None = None
    classification_correct: bool | None = None
    policy_correct: bool | None = None
    final_status_correct: bool | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


class ScenarioResultWriter:
    def __init__(self, path: Path | str = "logs/scenario_results.jsonl") -> None:
        self.path = Path(path)

    def write(self, result: ScenarioResult) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(result.to_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
