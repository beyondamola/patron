from __future__ import annotations

import signal
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from harness.config import DetectorConfig


class ManagedPatron:
    def __init__(
        self,
        target: str,
        scenario_id: str,
        interval: int = 1,
        trace: bool = False,
        log_root: Path | str = "logs/scenarios",
        config: DetectorConfig | None = None,
    ) -> None:
        self.target = target
        self.scenario_id = scenario_id
        self.interval = interval
        self.trace = trace
        self.config = config or DetectorConfig()
        self.config.validate_interval(interval)
        self.log_dir = Path(log_root) / scenario_id
        self.log_path = self.log_dir / "patron.log"
        self.config_path = self.log_dir / "detectors.json"
        self.process: subprocess.Popen | None = None
        self._log_handle = None

    def command(self) -> list[str]:
        command = [
            sys.executable,
            "-u",
            "-m",
            "harness",
            "watch",
            "--target",
            self.target,
            "--interval",
            str(self.interval),
            "--verbose",
            "--config",
            str(self.config_path.resolve()),
        ]
        if self.trace:
            command.append("--trace")
        return command

    def start(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self.config.to_dict(), sort_keys=True), encoding="utf-8")
        self._log_handle = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            self.command(),
            env={**os.environ, "PATRON_STATE_PATH": str(self.log_dir / "incident_state.json")},
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def wait_ready(self, timeout_seconds: int = 10) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.process and self.process.poll() is not None:
                return False
            if self.log_path.exists() and "[Collector]" in self.log_path.read_text(encoding="utf-8"):
                return True
            time.sleep(0.2)
        return False

    def stop(self, timeout_seconds: int = 10) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
        if self._log_handle:
            self._log_handle.close()
            self._log_handle = None
