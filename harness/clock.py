"""Time dependency for live execution and deterministic recorded evaluation."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def utc_now(self) -> str: ...
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
