from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def stage(name: str, message: str, enabled: bool) -> None:
    if not enabled:
        return
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}][{name}] {message}")


def trace_packet(label: str, payload: Any, enabled: bool) -> None:
    if not enabled:
        return
    print(f"[TRACE][{label}]")
    print(json.dumps(payload, indent=2, sort_keys=True))

