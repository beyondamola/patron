from __future__ import annotations

import math
import time
from typing import Callable

from ..collector import ContainerSnapshot
from ..config import DetectorConfig
from .base import Trigger


class ContainerHighCPUTrigger(Trigger):
    incident_type = "CONTAINER_HIGH_CPU"

    def __init__(self, threshold: float = 80.0, *, config: DetectorConfig | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.config = config or DetectorConfig(cpu_threshold=threshold)
        self.threshold = self.config.cpu_threshold
        self.clock = clock
        self._identity = None
        self._last_time = None
        self._last_restart_count = None
        self._high_start = self._low_start = None
        self._high_count = self._low_count = 0
        self._active = False
        self._snapshot = None
        self._trace = {}

    def _reset_windows(self) -> None:
        self._high_start = self._low_start = None
        self._high_count = self._low_count = 0

    def evaluate(self, snapshot: ContainerSnapshot) -> bool:
        return self.trace(snapshot)["result"]

    def build_metadata(self, snapshot: ContainerSnapshot) -> dict:
        return {
            **self.trace(snapshot),
            "reason": f"{snapshot.name} sustained CPU alarm at threshold {self.threshold}%",
            "observed_state": "high_cpu",
            "expected_state": "cpu_below_threshold",
            "cpu_percent": snapshot.cpu_percent,
            "threshold": self.threshold,
        }

    def trace(self, snapshot: ContainerSnapshot) -> dict:
        # Tracing and packet construction must not count one observation twice.
        if snapshot is self._snapshot:
            return dict(self._trace)
        self._snapshot = snapshot
        now = self.clock()
        stamp = snapshot.observed_monotonic if snapshot.observed_monotonic is not None else now
        identity = (snapshot.name, snapshot.container_id)
        if identity != self._identity:
            self._identity = identity
            self._last_time = self._last_restart_count = None
            self._active = False
            self._reset_windows()
        value = snapshot.cpu_percent
        reason = None
        if not _finite(stamp) or stamp > now or now - stamp > self.config.cpu_max_gap_seconds:
            reason = "invalid, future, or stale sample timestamp"
        elif self._last_time is not None and stamp <= self._last_time:
            reason = "duplicate or out-of-order sample"
        elif not snapshot.exists or not snapshot.running or not _finite(value) or value < 0:
            reason = "CPU unavailable or container not running"
        elif self._last_restart_count is not None and snapshot.restart_count < self._last_restart_count:
            reason = "restart counter reset"
        gap = stamp - self._last_time if _finite(stamp) and self._last_time is not None else None
        if gap is not None and gap > self.config.cpu_max_gap_seconds:
            self._reset_windows()
        if reason:
            self._reset_windows()
            result = False
        else:
            if value >= self.threshold:
                if self._high_start is None:
                    self._high_start = stamp
                self._high_count += 1
                self._low_start, self._low_count = None, 0
                if (self._high_count >= self.config.cpu_min_samples
                        and stamp - self._high_start >= self.config.cpu_window_seconds):
                    self._active = True
            elif value <= self.config.cpu_recovery_threshold:
                self._high_start, self._high_count = None, 0
                if self._low_start is None:
                    self._low_start = stamp
                self._low_count += 1
                if (self._low_count >= self.config.cpu_recovery_samples
                        and stamp - self._low_start >= self.config.cpu_recovery_seconds):
                    self._active = False
            else:
                self._reset_windows()
            result = self._active
            reason = "sustained alarm active" if result else "sustained high-load window not met"
        if _finite(stamp) and stamp <= now:
            # Preserve the watermark on out-of-order observations.
            self._last_time = max(stamp, self._last_time) if self._last_time is not None else stamp
        self._last_restart_count = snapshot.restart_count
        self._trace = {
            "incident_type": self.incident_type, "cpu_percent": value if _finite(value) else None,
            "running": snapshot.running, "threshold": self.threshold,
            "cpu_quota": snapshot.cpu_quota, "cpu_period": snapshot.cpu_period,
            "nano_cpus": snapshot.nano_cpus,
            "window_seconds": self.config.cpu_window_seconds,
            "minimum_samples": self.config.cpu_min_samples,
            "max_gap_seconds": self.config.cpu_max_gap_seconds,
            "sample_count": self._high_count,
            "coverage_seconds": stamp - self._high_start if self._high_start is not None else 0,
            "recovery_sample_count": self._low_count,
            "recovery_coverage_seconds": stamp - self._low_start if self._low_start is not None else 0,
            "recovery_threshold": self.config.cpu_recovery_threshold,
            "recovery_seconds": self.config.cpu_recovery_seconds,
            "recovery_minimum_samples": self.config.cpu_recovery_samples,
            "alarm_latched": self._active, "result": result, "reason": reason,
        }
        return dict(self._trace)


def _finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)
