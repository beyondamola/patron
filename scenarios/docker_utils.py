from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from .images import ALPINE, NGINX


SIMULATION_LABEL = "patron.simulation"
SCENARIO_LABEL = "patron.scenario"
SCENARIO_ID_LABEL = "patron.scenario_id"
MANAGED_LABEL = "patron.managed"


class DockerError(RuntimeError):
    pass


@dataclass(frozen=True)
class DockerResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ContainerState:
    name: str
    exists: bool
    running: bool
    status: str
    health: str | None
    exit_code: int | None
    restart_count: int
    labels: dict[str, str]
    container_id: str | None = None
    has_healthcheck: bool = False
    restart_policy: str | None = None
    oom_killed: bool = False


class DockerClient:
    def run(self, args: list[str], check: bool = True) -> DockerResult:
        try:
            result = subprocess.run(
                ["docker", *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DockerError(str(exc)) from exc
        wrapped = DockerResult(result.returncode, result.stdout.strip(), result.stderr.strip())
        if check and wrapped.returncode != 0:
            raise DockerError(wrapped.stderr or wrapped.stdout or f"docker {' '.join(args)} failed")
        return wrapped

    def inspect(self, name: str) -> ContainerState:
        result = self.run(["inspect", name], check=False)
        if result.returncode != 0:
            if "no such" not in result.stderr.lower():
                raise DockerError(result.stderr)
            return ContainerState(name, False, False, "missing", None, None, 0, {})
        payload = json.loads(result.stdout)[0]
        state = payload.get("State", {})
        config = payload.get("Config", {})
        host_config = payload.get("HostConfig", {})
        health = state.get("Health")
        healthcheck = config.get("Healthcheck")
        has_healthcheck = bool(health) or bool(healthcheck and healthcheck.get("Test"))
        return ContainerState(
            name=name,
            exists=True,
            running=bool(state.get("Running")),
            status=str(state.get("Status", "unknown")),
            health=(health or {}).get("Status") if has_healthcheck else None,
            exit_code=state.get("ExitCode"),
            restart_count=int(payload.get("RestartCount") or 0),
            labels=dict(config.get("Labels") or {}),
            container_id=payload.get("Id"),
            has_healthcheck=has_healthcheck,
            restart_policy=(host_config.get("RestartPolicy") or {}).get("Name"),
            oom_killed=bool(state.get("OOMKilled")),
        )

    def remove_container(self, name: str) -> None:
        self.run(["rm", "-f", name])

    def stop_container(self, name: str) -> None:
        self.run(["stop", name])

    def start_container(self, name: str) -> None:
        self.run(["start", name])

    def exec(self, name: str, command: list[str]) -> None:
        self.run(["exec", name, *command])

    def update_restart_policy(self, name: str, policy: str) -> None:
        self.run(["update", "--restart", policy, name], check=False)

    def cpu_percent(self, name: str) -> float | None:
        result = self.run(["stats", name, "--no-stream", "--format", "{{json .}}"], check=False)
        if result.returncode != 0 or not result.stdout:
            return None
        try:
            return float(json.loads(result.stdout).get("CPUPerc", "").rstrip("%"))
        except (ValueError, json.JSONDecodeError):
            return None

    def disk_usage_percent(self, name: str, path: str = "/patron-disk") -> float | None:
        result = self.run(
            ["exec", name, "df", "-P", "--", path],
            check=False,
        )
        if result.returncode != 0:
            return None
        try:
            return float(result.stdout.splitlines()[-1].split()[-2].rstrip("%"))
        except (ValueError, IndexError):
            return None

    def list_simulation_containers(self) -> list[str]:
        result = self.run(["ps", "-aq", "--filter", f"label={SIMULATION_LABEL}=true"], check=False)
        if result.returncode != 0 or not result.stdout:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def cleanup_simulation_containers(self) -> list[str]:
        ids = self.list_simulation_containers()
        for container_id in ids:
            self.update_restart_policy(container_id, "no")
            self.remove_container(container_id)
        return ids

    def remove_simulation_networks(self) -> list[str]:
        result = self.run(["network", "ls", "-q", "--filter", f"label={SIMULATION_LABEL}=true"], check=False)
        ids = [line.strip() for line in result.stdout.splitlines() if line.strip()] if result.stdout else []
        for network_id in ids:
            self.run(["network", "rm", network_id], check=False)
        return ids

    def ensure_nginx_running(self, name: str, labels: dict[str, str]) -> bool:
        state = self.inspect(name)
        if state.exists:
            if not state.running:
                self.start_container(name)
            return False
        args = ["run", "-d", "--name", name]
        for key, value in labels.items():
            args.extend(["--label", f"{key}={value}"])
        args.extend([NGINX])
        self.run(args)
        return True

    def create_nginx_container(self, name: str, labels: dict[str, str]) -> None:
        state = self.inspect(name)
        if state.exists and state.labels.get(SIMULATION_LABEL) != "true":
            raise DockerError(
                f"Cannot create {name} because that name belongs to a non-simulation container. "
                "Choose another target with --target."
            )
        if state.exists:
            self.remove_container(name)
        args = ["run", "-d", "--name", name, "--restart", "no"]
        for key, value in labels.items():
            args.extend(["--label", f"{key}={value}"])
        args.append(NGINX)
        self.run(args)

    def create_healthcheck_container(self, name: str, labels: dict[str, str]) -> None:
        state = self.inspect(name)
        if state.exists and state.labels.get(SIMULATION_LABEL) != "true":
            raise DockerError(
                f"Cannot create {name} because that name belongs to a non-simulation container. "
                "Choose another target with --target."
            )
        if state.exists:
            self.remove_container(name)
        args = ["run", "-d", "--name", name]
        for key, value in labels.items():
            args.extend(["--label", f"{key}={value}"])
        args.extend(
            [
                "--health-cmd",
                "test -f /tmp/patron-health",
                "--health-interval",
                "1s",
                "--health-timeout",
                "1s",
                "--health-retries",
                "2",
                ALPINE,
                "sh",
                "-c",
                "touch /tmp/patron-health; while true; do sleep 60; done",
            ]
        )
        self.run(args)

    def create_restart_loop_container(self, name: str, labels: dict[str, str]) -> None:
        state = self.inspect(name)
        if state.exists and state.labels.get(SIMULATION_LABEL) != "true":
            raise DockerError(
                f"Cannot create {name} because that name belongs to a non-simulation container. "
                "Choose another target with --target."
            )
        if state.exists:
            self.remove_container(name)
        args = ["run", "-d", "--name", name, "--restart", "always"]
        for key, value in labels.items():
            args.extend(["--label", f"{key}={value}"])
        args.extend([ALPINE, "sh", "-c", "sleep 1; exit 1"])
        self.run(args)

    def create_oom_container(self, name: str, labels: dict[str, str]) -> None:
        self._remove_existing_simulation_or_fail(name)
        args = ["run", "-d", "--name", name, "--memory", "32m", "--memory-swap", "32m",
                "--cpus", "1", "--pids-limit", "32"]
        self._append_labels(args, labels)
        # Keep PID 1 alive briefly after the high-memory child dies, so the OOM
        # event can be observed before task teardown. Exit status is not proof of OOM.
        args.extend([ALPINE, "sh", "-c", "while [ ! -f /tmp/inject-oom ]; do sleep 0.1; done; "
                     "awk 'BEGIN{s=\"x\"; while(1){s=s s}}'; code=$?; sleep 5; exit \"$code\""])
        self.run(args)

    def create_cpu_container(self, name: str, labels: dict[str, str]) -> None:
        self._remove_existing_simulation_or_fail(name)
        args = ["run", "-d", "--name", name, "--cpus", "1", "--memory", "64m", "--pids-limit", "32"]
        self._append_labels(args, labels)
        args.extend([ALPINE, "sh", "-c", "while true; do sleep 60; done"])
        self.run(args)

    def create_disk_container(self, name: str, labels: dict[str, str]) -> None:
        self._remove_existing_simulation_or_fail(name)
        labels = {**labels, "patron.disk_path": "/patron-disk"}
        args = ["run", "-d", "--name", name, "--tmpfs", "/patron-disk:size=16m"]
        self._append_labels(args, labels)
        args.extend([ALPINE, "sh", "-c", "while true; do sleep 60; done"])
        self.run(args)

    def create_bad_config_container(self, name: str, labels: dict[str, str]) -> None:
        self._remove_existing_simulation_or_fail(name)
        command = (
            "echo valid > /tmp/app.conf; "
            "while true; do "
            "if grep -q invalid /tmp/app.conf; then echo CONFIG_ERROR invalid config; exit 1; fi; "
            "sleep 1; done"
        )
        args = ["run", "-d", "--name", name]
        self._append_labels(args, labels)
        args.extend([ALPINE, "sh", "-c", command])
        self.run(args)

    def create_dependency_environment(
        self,
        app_name: str,
        dependency_name: str,
        network_name: str,
        labels: dict[str, str],
    ) -> None:
        self._remove_existing_simulation_or_fail(app_name)
        self._remove_existing_simulation_or_fail(dependency_name)
        self.remove_owned_network(network_name)
        network_args = ["network", "create"]
        self._append_labels(network_args, labels)
        network_args.append(network_name)
        self.run(network_args)

        dep_args = ["run", "-d", "--name", dependency_name, "--network", network_name, "--network-alias", "dependency"]
        self._append_labels(dep_args, labels)
        dep_args.append(NGINX)
        self.run(dep_args)

        app_labels = {**labels, "patron.dependency": dependency_name}
        app_args = ["run", "-d", "--name", app_name, "--network", network_name]
        self._append_labels(app_args, app_labels)
        app_args.extend(
            [
                "--health-cmd",
                "wget -T 1 -q -O- http://dependency:80 >/dev/null || exit 1",
                "--health-interval",
                "1s",
                "--health-timeout",
                "1s",
                "--health-retries",
                "2",
                ALPINE,
                "sh",
                "-c",
                "while true; do wget -T 1 -q -O- http://dependency:80 >/dev/null || echo DEPENDENCY_DOWN dependency unavailable; sleep 1; done",
            ]
        )
        self.run(app_args)

    def _append_labels(self, args: list[str], labels: dict[str, str]) -> None:
        for key, value in labels.items():
            args.extend(["--label", f"{key}={value}"])

    def remove_owned_network(self, name: str, scenario_id: str | None = None) -> None:
        result = self.run(["network", "inspect", name], check=False)
        if result.returncode != 0:
            if "not found" in result.stderr.lower() or "no such" in result.stderr.lower():
                return
            raise DockerError(result.stderr)
        labels = json.loads(result.stdout)[0].get("Labels") or {}
        if labels.get(SIMULATION_LABEL) != "true":
            raise DockerError(f"Refusing to remove non-simulation network {name}")
        if scenario_id and labels.get(SCENARIO_ID_LABEL) != scenario_id:
            return
        self.run(["network", "rm", name])

    def _remove_existing_simulation_or_fail(self, name: str) -> None:
        state = self.inspect(name)
        if state.exists and state.labels.get(SIMULATION_LABEL) != "true":
            raise DockerError(
                f"Cannot create {name} because that name belongs to a non-simulation container. "
                "Choose another target with --target."
            )
        if state.exists:
            self.remove_container(name)


def docker_available(client: DockerClient | None = None) -> bool:
    if shutil.which("docker") is None:
        return False
    client = client or DockerClient()
    return client.run(["version", "--format", "{{json .Server.Version}}"], check=False).returncode == 0


def simulation_labels(scenario_name: str, scenario_id: str) -> dict[str, str]:
    labels = {
        SIMULATION_LABEL: "true",
        SCENARIO_LABEL: scenario_name,
        SCENARIO_ID_LABEL: scenario_id,
        MANAGED_LABEL: "true",
    }
    if os.environ.get("PATRON_CI_RUN_ID"):
        labels["patron.ci_run_id"] = os.environ["PATRON_CI_RUN_ID"]
    return labels


def is_simulation_resource(state: ContainerState, scenario_id: str | None = None) -> bool:
    if state.labels.get(SIMULATION_LABEL) != "true":
        return False
    if scenario_id is None:
        return True
    return state.labels.get(SCENARIO_ID_LABEL) == scenario_id


def normalized_state_packet(state: ContainerState) -> dict:
    return {
        "name": state.name,
        "id": state.container_id,
        "exists": state.exists,
        "status": state.status,
        "running": state.running,
        "exit_code": state.exit_code,
        "restart_count": state.restart_count,
        "health_status": state.health or "none",
        "has_healthcheck": state.has_healthcheck,
        "restart_policy": state.restart_policy,
        "labels": state.labels,
        "oom_killed": state.oom_killed,
    }


def wait_until(
    predicate: Callable[[], bool],
    timeout_seconds: int,
    poll_interval_seconds: float = 1.0,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll_interval_seconds)
    return predicate()
