from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class AuditLogger:
    def __init__(self, path: Path | str = "logs/incidents.jsonl") -> None:
        self.path = Path(path)

    def log(self, incident: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(incident, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
