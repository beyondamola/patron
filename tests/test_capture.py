import json
from dataclasses import replace

import pytest

from harness.capture import CaptureWriter, normalized_snapshot, read_capture
from harness.collector import ContainerSnapshot
from harness.config import DetectorConfig


class Clock:
    def utc_now(self):
        return "2026-09-11T00:00:00+00:00"

    def monotonic(self):
        return 100.0


def write_capture(path):
    writer = CaptureWriter(path, config=DetectorConfig(), initial_state={"schema_version": 1},
                           clock=Clock(), run_id="test-run")
    try:
        writer.observe(ContainerSnapshot("test", True, True, "running", {}, observed_monotonic=100))
        writer.emit("run_end", {})
    finally:
        writer.close()


def test_capture_omits_raw_env_labels_and_redacts_bounded_logs():
    snapshot = ContainerSnapshot("test", True, True, "running",
        {"Env": ["PASSWORD=private"]}, labels={"arbitrary": "private"},
        recent_logs=["token=abcdef", "https://user:private@host/path"] + ["x" * 2000] * 19,
        observed_monotonic=105, cpu_percent=float("nan"))
    packet = normalized_snapshot(snapshot, 100)
    encoded = json.dumps(packet, allow_nan=False)
    assert "raw" not in packet and "labels" not in packet and "private" not in encoded
    assert packet["observed_monotonic"] == 5 and packet["cpu_percent"] is None
    assert len(packet["recent_logs"]) == 20 and max(map(len, packet["recent_logs"])) == 1000
    assert "[REDACTED]" in encoded
    assert normalized_snapshot(replace(snapshot, recent_logs=["token=abcdef"]), 100)["recent_logs"] == ["token=[REDACTED]"]


def test_capture_round_trip_and_exclusive_create(tmp_path):
    path = tmp_path / "capture.jsonl"
    write_capture(path)
    records = read_capture(path)
    assert [record["sequence"] for record in records] == [0, 1, 2]
    assert records[1]["payload"]["snapshot"]["observed_monotonic"] == 0
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_capture(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("change,message", [
    (lambda rows: rows[1].update(sequence=9), "sequence"),
    (lambda rows: rows[1].update(schema_version=99), "schema"),
    (lambda rows: rows[1].update(monotonic_offset=-1), "offset"),
    (lambda rows: rows[1].update(run_id="other"), "identity"),
    (lambda rows: rows[0]["payload"].pop("initial_state"), "initial state"),
    (lambda rows: rows[0]["payload"].update(config_fingerprint="wrong"), "fingerprint"),
    (lambda rows: rows.pop(), "run_end"),
])
def test_invalid_capture_rejected(tmp_path, change, message):
    path = tmp_path / "capture.jsonl"
    write_capture(path)
    rows = read_capture(path)
    change(rows)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match=message):
        read_capture(path)


def test_partial_final_write_is_explicitly_incomplete(tmp_path):
    path = tmp_path / "capture.jsonl"
    write_capture(path)
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError, match="incomplete final"):
        read_capture(path)


@pytest.mark.parametrize("text", ['{"schema_version":1,"schema_version":1}\n',
                                  '{"schema_version":true}\n',
                                  '{"value":1e999}\n'])
def test_ambiguous_json_or_nonfinite_number_rejected(tmp_path, text):
    path = tmp_path / "capture.jsonl"
    path.write_text(text)
    with pytest.raises(ValueError):
        read_capture(path)
