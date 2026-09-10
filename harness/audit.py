from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from .storage import StateLock


class AuditLogger:
    def __init__(self, path: Path | str = "logs/incidents.jsonl") -> None:
        self.path = Path(path)

    def log(self, incident: dict[str, Any]) -> None:
        with StateLock(self.path.resolve()).acquire():
            self._log_owned(incident)

    def _log_owned(self, incident: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size:
            with self.path.open("rb") as stream:
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    raise ValueError("Audit has an incomplete tail; preserve and repair it before appending")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(incident, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
