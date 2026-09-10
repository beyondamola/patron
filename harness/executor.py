from __future__ import annotations

import subprocess
from typing import Any


class DockerExecutor:
    """Executes approved remediation actions against local Docker."""

    def execute(self, plan: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "restart_container": self._restart_container,
            "escalate": self._escalate,
        }
        action = plan["decision"]
        handler = handlers.get(action)
        if handler is None:
            raise ValueError(f"unsupported action: {action}")
        return handler(context)

    def _restart_container(self, context: dict[str, Any]) -> dict[str, Any]:
        action = "restart_container"
        container_name = context["resource"]
        try:
            result = subprocess.run(
                ["docker", "restart", container_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "action": action,
                "target": container_name,
                "returncode": 127,
                "stdout": "",
                "stderr": str(exc),
                "success": False,
            }
        return {
            "action": action,
            "target": container_name,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "success": result.returncode == 0,
        }

    def _escalate(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "action": "escalate",
            "target": context["resource"],
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "success": True,
        }
