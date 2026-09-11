"""Validated detector settings shared by live detection and recorded evaluation."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class DetectorConfig:
    restart_loop_threshold: int = 3
    disk_threshold: float = 90.0
    cpu_threshold: float = 80.0
    cpu_window_seconds: float = 10.0
    cpu_min_samples: int = 3
    cpu_max_gap_seconds: float = 15.0
    cpu_recovery_threshold: float = 60.0
    cpu_recovery_seconds: float = 5.0
    cpu_recovery_samples: int = 2
    log_evidence_seconds: float = 60.0
    disk_path: str | None = None
    dependency: str | None = None

    def __post_init__(self) -> None:
        counts = {"restart_loop_threshold": 1, "cpu_min_samples": 2, "cpu_recovery_samples": 2}
        for key, value in asdict(self).items():
            if key in ("disk_path", "dependency"):
                if value is not None and (not isinstance(value, str) or not value.strip()
                                          or len(value) > 1024 or "\x00" in value):
                    raise ValueError(f"{key} must be a nonempty bounded string or null")
            elif key in counts:
                if type(value) is not int or value < counts[key]:
                    raise ValueError(f"{key} must be an integer >= {counts[key]}")
            elif type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be a positive finite number")
        if self.disk_threshold > 100:
            raise ValueError("disk_threshold cannot exceed 100 percent")
        if self.cpu_recovery_threshold >= self.cpu_threshold:
            raise ValueError("cpu_recovery_threshold must be below cpu_threshold")
        if self.disk_path is not None and not self.disk_path.startswith("/"):
            raise ValueError("disk_path must be absolute")

    def to_dict(self) -> dict:
        return asdict(self)

    def validate_interval(self, interval: float) -> None:
        if (type(interval) not in (int, float) or not math.isfinite(interval)
                or interval <= 0 or interval >= self.cpu_max_gap_seconds):
            raise ValueError("poll interval must be positive and below cpu_max_gap_seconds; allow time for collection")

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(payload.encode()).hexdigest()

    @classmethod
    def load(cls, path: str | Path) -> DetectorConfig:
        payload = json.loads(Path(path).read_text())
        if not isinstance(payload, dict):
            raise ValueError("detector configuration must be a JSON object")
        try:
            return cls(**payload)
        except TypeError as exc:
            raise ValueError(f"invalid detector configuration: {exc}") from exc
