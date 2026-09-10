from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any


def docker_run(args, **kwargs):
    try:
        return subprocess.run(args, timeout=10, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


@dataclass(frozen=True)
class ContainerSnapshot:
    name: str
    exists: bool
    running: bool
    status: str
    raw: dict[str, Any]
    exit_code: int | None = None
    health: str | None = None
    restart_count: int = 0
    container_id: str | None = None
    has_healthcheck: bool = False
    restart_policy: str | None = None
    labels: dict[str, str] | None = None
    oom_killed: bool = False
    memory_limit_bytes: int | None = None
    memory_usage_bytes: int | None = None
    cpu_percent: float | None = None
    disk_usage_percent: float | None = None
    recent_logs: list[str] | None = None
    error_patterns: list[str] | None = None
    ports: list[str] | None = None
    network_mode: str | None = None
    dependency_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Collector(ABC):
    @abstractmethod
    def collect(self) -> ContainerSnapshot:
        raise NotImplementedError


class DockerCollector(Collector):
    """Collects container state from the local Docker daemon."""

    def __init__(self, container_name: str = "mvp-nginx") -> None:
        self.container_name = container_name

    def collect(self) -> ContainerSnapshot:
        try:
            result = docker_run(
                ["docker", "inspect", self.container_name],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return ContainerSnapshot(
                name=self.container_name,
                exists=False,
                running=False,
                status="docker_unavailable",
                raw={"stderr": "docker CLI not found"},
            )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            status = "missing" if "no such" in stderr.lower() else "inspect_failed"
            return ContainerSnapshot(
                name=self.container_name,
                exists=False,
                running=False,
                status=status,
                raw={"stderr": stderr},
            )

        snapshot = snapshot_from_docker_inspect(self.container_name, json.loads(result.stdout)[0])
        return enrich_snapshot(self.container_name, snapshot)


def snapshot_from_docker_inspect(container_name: str, payload: dict[str, Any]) -> ContainerSnapshot:
    state = payload.get("State", {})
    config = payload.get("Config", {})
    host_config = payload.get("HostConfig", {})
    health = state.get("Health")
    healthcheck = config.get("Healthcheck")
    has_healthcheck = bool(health) or bool(healthcheck and healthcheck.get("Test") and healthcheck["Test"] != ["NONE"])
    restart_policy = (host_config.get("RestartPolicy") or {}).get("Name")
    labels = dict(config.get("Labels") or {})
    ports = sorted((config.get("ExposedPorts") or {}).keys())
    return ContainerSnapshot(
        name=container_name,
        exists=True,
        running=bool(state.get("Running")),
        status=str(state.get("Status", "unknown")),
        raw=state,
        exit_code=state.get("ExitCode"),
        health=(health or {}).get("Status") if has_healthcheck else None,
        restart_count=int(payload.get("RestartCount") or 0),
        container_id=payload.get("Id"),
        has_healthcheck=has_healthcheck,
        restart_policy=restart_policy,
        labels=labels,
        oom_killed=bool(state.get("OOMKilled")),
        memory_limit_bytes=host_config.get("Memory") or None,
        recent_logs=[],
        error_patterns=[],
        ports=ports,
        network_mode=host_config.get("NetworkMode"),
        dependency_status=None,
    )


def enrich_snapshot(container_name: str, snapshot: ContainerSnapshot) -> ContainerSnapshot:
    if not snapshot.exists:
        return snapshot
    logs = collect_recent_logs(container_name)
    patterns = detect_error_patterns(logs)
    cpu = collect_cpu_percent(container_name)
    disk = collect_disk_usage_percent(container_name, (snapshot.labels or {}).get("patron.disk_path", "/tmp"))
    dependency_status = collect_dependency_status((snapshot.labels or {}).get("patron.dependency"))
    return ContainerSnapshot(
        **{
            **snapshot.to_dict(),
            "recent_logs": logs,
            "error_patterns": patterns,
            "cpu_percent": cpu,
            "disk_usage_percent": disk,
            "dependency_status": dependency_status,
        }
    )


def collect_recent_logs(container_name: str) -> list[str]:
    result = docker_run(
        ["docker", "logs", "--tail", "20", container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line[:1000] for line in (result.stdout + result.stderr).splitlines() if line][-20:]


def detect_error_patterns(logs: list[str]) -> list[str]:
    joined = "\n".join(logs).lower()
    patterns = []
    if "config_error" in joined or "invalid config" in joined:
        patterns.append("bad_config")
    if "connection refused" in joined or "dependency_down" in joined or "dependency unavailable" in joined:
        patterns.append("dependency_down")
    if "no space left" in joined or "disk full" in joined:
        patterns.append("disk_full")
    return patterns


def collect_cpu_percent(container_name: str) -> float | None:
    result = docker_run(
        ["docker", "stats", container_name, "--no-stream", "--format", "{{json .}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stdout)
        return float(str(payload.get("CPUPerc", "")).strip().rstrip("%"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def collect_disk_usage_percent(container_name: str, path: str) -> float | None:
    result = docker_run(
        ["docker", "exec", container_name, "df", "-P", "--", path],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    lines = result.stdout.splitlines()
    value = lines[-1].split()[-2].rstrip("%") if len(lines) >= 2 else ""
    try:
        return float(value)
    except ValueError:
        return None


def collect_dependency_status(dependency_name: str | None) -> str | None:
    if not dependency_name:
        return None
    result = docker_run(
        ["docker", "inspect", dependency_name],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return "missing"
    try:
        state = json.loads(result.stdout)[0].get("State", {})
    except (json.JSONDecodeError, IndexError):
        return "unknown"
    return "running" if state.get("Running") else "down"
