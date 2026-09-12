"""Optional lab provenance, kept separate from captured runtime measurements."""
from datetime import datetime
import json
from pathlib import Path

from .capture import read_capture


def _utc(value):
    if not isinstance(value, str):
        raise ValueError("scenario provenance timestamp must be an ISO-8601 string")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("scenario provenance timestamp must include a timezone")
    return stamp


def lab_provenance(capture_path, results_path) -> dict:
    records = read_capture(capture_path)
    header = records[0]["payload"]
    incidents = {}
    for record in records:
        if record["event"] == "transition":
            incident = record["payload"]["incident"]
            incidents.setdefault(incident["incident_id"], incident)
    matches = []
    path = Path(results_path)
    if path.stat().st_size > 64_000_000:
        raise ValueError("scenario results exceed the 64MB provenance input limit")
    with path.open(encoding="utf-8") as handle:
        while True:
            line = handle.readline(65_537)
            if not line:
                break
            if len(line) > 65_536 or not line.endswith("\n"):
                raise ValueError("scenario results contain an oversized or incomplete record")
            result = json.loads(line)
            if not isinstance(result, dict):
                raise ValueError("scenario result must be a JSON object")
            identifier = result.get("patron_incident_id")
            if identifier is not None and not isinstance(identifier, str):
                raise ValueError("scenario incident identity must be a string or null")
            incident = incidents.get(identifier)
            if incident is None:
                continue
            if (result.get("target") != header["runtime_settings"]["target"]
                    or result.get("observed_incident_type") != incident["incident_type"]
                    or result.get("detector_config_fingerprint") != header["config_fingerprint"]):
                raise ValueError("scenario provenance does not match captured target, type, or configuration")
            if not isinstance(result.get("scenario_id"), str) or not result["scenario_id"]:
                raise ValueError("scenario provenance lacks scenario identity")
            injected = result.get("injected_at")
            delay = None
            onset_precedes_capture = None
            if injected is not None:
                onset = _utc(injected)
                detected = _utc(incident["created_at"])
                if not (onset <= detected and _utc(records[0]["utc_time"]) <= detected <= _utc(records[-1]["utc_time"])):
                    raise ValueError("scenario detection is outside the captured run or precedes injection")
                onset_precedes_capture = onset < _utc(records[0]["utc_time"])
                if result.get("failure_observed") is not True or result.get("failure_injected") is not True:
                    raise ValueError("scenario provenance does not confirm the injected failure")
                delay = (detected - onset).total_seconds()
            matches.append({"scenario_id": result["scenario_id"],
                "incident_id": incident["incident_id"], "incident_type": incident["incident_type"],
                "target": result["target"], "injected_at": injected,
                "onset_precedes_capture": onset_precedes_capture,
                "detected_at": incident["created_at"], "detection_latency_seconds": delay})
    if not matches:
        raise ValueError("no scenario result matches an incident in this capture")
    if len({item["incident_id"] for item in matches}) != len(matches):
        raise ValueError("ambiguous duplicate scenario results for a captured incident")
    return {"source": "explicitly supplied lab results; not runtime onset knowledge",
        "clock_basis": "UTC timestamps; assumes lab and runtime clocks are aligned",
        "candidate_detection_latency_seconds": None, "incidents": matches}
