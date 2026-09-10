"""Fail-closed CI preflight, result validation, and run-scoped cleanup."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import xml.etree.ElementTree as ET

from scenarios.docker_utils import DockerClient, DockerError
from scenarios.images import IMAGES
from scenarios.registry import default_registry


def prepare(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    client = DockerClient()
    version = client.run(["version", "--format", "{{json .}}"])
    environment = {"python": platform.python_version(), "host": platform.platform(),
                   "docker": json.loads(version.stdout), "images": list(IMAGES)}
    (destination / "environment.json").write_text(json.dumps(environment, indent=2))
    for image in IMAGES:
        result = subprocess.run(["docker", "pull", image], capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise DockerError(f"Image pre-pull failed for {image}: {result.stderr}")


def validate_report(path: Path) -> None:
    cases = ET.parse(path).getroot().findall(".//testcase")
    expected = {f"test_real_scenario[{name}]" for name in default_registry().names()}
    names = [case.get("name") for case in cases]
    if len(cases) != len(expected) or set(names) != expected:
        raise ValueError(f"Expected exactly these eight scenarios: {sorted(expected)}; got {names}")
    if any(case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped")):
        raise ValueError("Integration report contains failures, errors, or skips")


def cleanup(run_id: str, client: DockerClient | None = None) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id):
        raise ValueError("A nonempty alphanumeric CI run ID is required for cleanup")
    client = client or DockerClient()
    for kind, listing in (("container", ["ps", "-aq"]),
                          ("network", ["network", "ls", "-q"]),
                          ("volume", ["volume", "ls", "-q"])):
        query = [*listing, "--filter", "label=patron.simulation=true",
                 "--filter", f"label=patron.ci_run_id={run_id}"]
        for identifier in client.run(query).stdout.splitlines():
            payload = json.loads(client.run([kind, "inspect", identifier]).stdout)[0]
            labels = (payload.get("Config", {}) if kind == "container" else payload).get("Labels") or {}
            if labels.get("patron.simulation") != "true" or labels.get("patron.ci_run_id") != run_id:
                raise DockerError(f"Refusing cleanup of ownership-mismatched {kind} {identifier}")
            client.run([kind, "rm", *(["-f"] if kind == "container" else []), identifier])
        if client.run(query).stdout:
            raise DockerError(f"Cleanup left {kind} resources for {run_id}")


def redact(text: str) -> str:
    text = re.sub(r"(?i)(authorization[\s\"':=]+(?:bearer\s+)?)[^\s\",]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:password|token|secret|api_key)[\s\"':=]+)[^\s\",]+", r"\1[REDACTED]", text)
    return re.sub(r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})", "[REDACTED]", text)


def collect_artifacts(destination: Path) -> None:
    # Only known local lab output; never traverse arbitrary paths or symlinks.
    for root in (Path("logs"), Path("artifacts/raw")):
        if not root.exists():
            continue
        for source in root.rglob("*"):
            if source.is_symlink() or not source.is_file() or source.suffix not in {".log", ".jsonl", ".json", ".xml"}:
                continue
            if any(parent.is_symlink() for parent in source.parents):
                continue
            target = destination / root.name / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(encoding="utf-8", errors="replace") as stream:
                content = stream.read(2_000_001)
            truncated = len(content) > 2_000_000
            target.write_text(redact(content[:2_000_000]), encoding="utf-8")
            if truncated:
                target.with_suffix(target.suffix + ".truncated").write_text("Artifact truncated at 2MB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "validate", "cleanup", "artifacts"))
    parser.add_argument("--path", type=Path, default=Path("artifacts/raw"))
    args = parser.parse_args()
    if args.operation == "prepare":
        prepare(args.path)
    elif args.operation == "validate":
        validate_report(args.path)
    elif args.operation == "cleanup":
        cleanup(os.environ.get("PATRON_CI_RUN_ID", ""))
    else:
        collect_artifacts(args.path)


if __name__ == "__main__":
    main()
