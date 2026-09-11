from __future__ import annotations

import json
import math
import re
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import DetectorConfig


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
    observed_monotonic: float | None = None
    started_at: str | None = None
    cpu_quota: int | None = None
    cpu_period: int | None = None
    nano_cpus: int | None = None
    probe_errors: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Collector(ABC):
    @abstractmethod
    def collect(self) -> ContainerSnapshot:
        raise NotImplementedError


class DockerCollector(Collector):
    """Collects container state from the local Docker daemon."""

    def __init__(self, container_name: str = "mvp-nginx", *, config: DetectorConfig | None = None) -> None:
        self.container_name = container_name
        self.config = config or DetectorConfig()

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
        enriched = enrich_snapshot(self.container_name, snapshot, config=self.config)
        # Logs/stats take time; do not act on an exit snapshot taken before OOM metadata settled.
        if not snapshot.running and not snapshot.oom_killed and snapshot.container_id:
            latest = docker_run(["docker", "inspect", snapshot.container_id],
                                check=False, capture_output=True, text=True)
            if latest.returncode:
                return ContainerSnapshot(self.container_name, False, False, "inspect_failed",
                                         {"stderr": latest.stderr})
            confirmed = snapshot_from_docker_inspect(self.container_name, json.loads(latest.stdout)[0])
            same_start = confirmed.started_at == enriched.started_at
            return replace(confirmed, recent_logs=enriched.recent_logs if same_start else [],
                           error_patterns=enriched.error_patterns if same_start else [],
                           cpu_percent=enriched.cpu_percent, disk_usage_percent=enriched.disk_usage_percent,
                           dependency_status=enriched.dependency_status,
                           probe_errors=enriched.probe_errors, observed_monotonic=enriched.observed_monotonic)
        return enriched


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
        started_at=state.get("StartedAt"),
        cpu_quota=host_config.get("CpuQuota") or None,
        cpu_period=host_config.get("CpuPeriod") or None,
        nano_cpus=host_config.get("NanoCpus") or None,
    )


def enrich_snapshot(container_name: str, snapshot: ContainerSnapshot, *, config: DetectorConfig | None = None) -> ContainerSnapshot:
    config = config or DetectorConfig()
    if not snapshot.exists:
        return snapshot
    target = snapshot.container_id or container_name
    errors = {}
    logs = collect_recent_logs(target, started_at=snapshot.started_at,
                               max_age_seconds=config.log_evidence_seconds, errors=errors)
    patterns = detect_error_patterns(logs)
    cpu = collect_cpu_percent(target)
    observed_monotonic = time.monotonic()
    disk = collect_disk_usage_percent(target, config.disk_path or (snapshot.labels or {}).get("patron.disk_path", "/tmp"))
    dependency_status = collect_dependency_status(config.dependency or (snapshot.labels or {}).get("patron.dependency"))
    if cpu is None:
        errors["cpu"] = "stats unavailable or invalid CPU percentage"
    if disk is None:
        errors["disk"] = "df probe unavailable, unsupported, or invalid for configured path"
    if dependency_status == "unknown":
        errors["dependency"] = "dependency inspect unavailable or missing valid running state"
    return ContainerSnapshot(
        **{
            **snapshot.to_dict(),
            "recent_logs": logs,
            "error_patterns": patterns,
            "cpu_percent": cpu,
            "disk_usage_percent": disk,
            "dependency_status": dependency_status,
            "probe_errors": errors,
            "observed_monotonic": observed_monotonic,
        }
    )


def parse_timestamp(value: str | None) -> datetime | None:
    try:
        # Docker emits nanoseconds; Python 3.9 accepts only microsecond precision.
        normalized = re.sub(r"(\.\d{6})\d+(?=Z|[+-]\d\d:\d\d$)", r"\1", value)
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def collect_recent_logs(container_name: str, *, started_at: str | None = None,
                        max_age_seconds: float = 60, now: datetime | None = None,
                        errors: dict | None = None) -> list[str]:
    errors = errors if errors is not None else {}
    now = now or datetime.now(timezone.utc)
    start = parse_timestamp(started_at)
    if start is None or start.year < 1970 or start > now:
        errors["logs"] = "current container start timestamp unavailable or invalid"
        return []
    cutoff = max(start, now - timedelta(seconds=max_age_seconds))
    result = docker_run(
        ["docker", "logs", "--timestamps", "--since", cutoff.isoformat(), "--tail", "20", container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        errors["logs"] = "Docker logs unavailable"
        return []
    logs = []
    for line in (result.stdout + "\n" + result.stderr).splitlines():
        stamp, separator, message = line.partition(" ")
        timestamp = parse_timestamp(stamp)
        if timestamp is not None and cutoff <= timestamp <= now and separator:
            logs.append((timestamp, message[:1000]))
        elif line:
            errors["logs_filtered"] = "discarded undated, stale, pre-start, or future log entries"
    return [message for _, message in sorted(logs, key=lambda item: item[0])[-20:]]


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
        value = float(str(payload.get("CPUPerc", "")).strip().rstrip("%"))
        return value if math.isfinite(value) and value >= 0 else None
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return None


def collect_disk_usage_percent(container_name: str, path: str) -> float | None:
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 1024 or "\x00" in path:
        return None
    result = docker_run(
        ["docker", "exec", container_name, "df", "-P", "--", path],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    lines = result.stdout.splitlines()
    try:
        value = float(lines[-1].split()[-2].rstrip("%")) if len(lines) >= 2 else None
        return value if value is not None and math.isfinite(value) and 0 <= value <= 100 else None
    except (ValueError, IndexError):
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
        return "unknown"
    try:
        state = json.loads(result.stdout)[0].get("State", {})
    except (json.JSONDecodeError, IndexError, TypeError, AttributeError, KeyError):
        return "unknown"
    if not isinstance(state, dict) or type(state.get("Running")) is not bool:
        return "unknown"
    return "running" if state["Running"] else "down"
