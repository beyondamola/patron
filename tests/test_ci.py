import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ci.checks import cleanup, collect_artifacts, prepare, redact, validate_report
from scenarios.docker_utils import DockerError, DockerResult, simulation_labels
from scenarios.images import IMAGES
from scenarios.registry import default_registry


def report(path, defect=None):
    suite = ET.Element("testsuite")
    for name in default_registry().names():
        case = ET.SubElement(suite, "testcase", name=f"test_real_scenario[{name}]")
        if defect and name == "stopped":
            ET.SubElement(case, defect)
    ET.ElementTree(suite).write(path)


@pytest.mark.parametrize("defect", ["skipped", "failure", "error"])
def test_report_rejects_unsuccessful_case(tmp_path, defect):
    path = tmp_path / "report.xml"
    report(path, defect)
    with pytest.raises(ValueError):
        validate_report(path)


def test_report_requires_all_eight(tmp_path):
    path = tmp_path / "report.xml"
    report(path)
    validate_report(path)
    path.write_text("<testsuite />")
    with pytest.raises(ValueError):
        validate_report(path)


def test_pins_and_run_labels(monkeypatch):
    assert all("@sha256:" in image and len(image.split(":")[-1]) == 64 for image in IMAGES)
    monkeypatch.setenv("PATRON_CI_RUN_ID", "job-1")
    assert simulation_labels("stopped", "scenario")["patron.ci_run_id"] == "job-1"


class FakeDocker:
    def __init__(self, owned=True):
        self.owned = owned
        self.removed = False
        self.calls = []

    def run(self, args):
        self.calls.append(args)
        if "inspect" in args:
            return DockerResult(0, json.dumps([{"Config": {"Labels": {
                "patron.simulation": "true", "patron.ci_run_id": "job-1" if self.owned else "other",
            }}}]), "")
        if "rm" in args:
            self.removed = True
        if args[0] == "ps" and not self.removed:
            return DockerResult(0, "owned-container", "")
        return DockerResult(0, "", "")


def test_cleanup_rechecks_ownership():
    client = FakeDocker(False)
    with pytest.raises(DockerError):
        cleanup("job-1", client)
    assert not client.removed


def test_cleanup_filters_exact_run():
    client = FakeDocker()
    cleanup("job-1", client)
    assert client.removed
    for call in client.calls:
        if "--filter" in call:
            assert "label=patron.simulation=true" in call
            assert "label=patron.ci_run_id=job-1" in call


def test_cleanup_never_accepts_empty_run():
    with pytest.raises(ValueError):
        cleanup("", FakeDocker())


def test_cleanup_accepts_real_workflow_run_id():
    client = FakeDocker()
    client.removed = True
    cleanup("34498459240-1-ubuntu-24.04-arm", client)
    assert all("label=patron.ci_run_id=34498459240-1-ubuntu-24.04-arm" in call for call in client.calls)


def test_redaction():
    assert "secret-value" not in redact('{"token": "secret-value"}')
    assert "abcd" not in redact("Authorization: Bearer abcd")


def test_unavailable_docker_fails_preflight(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise DockerError("Docker daemon unavailable")
    monkeypatch.setattr("ci.checks.DockerClient.run", unavailable)
    with pytest.raises(DockerError, match="unavailable"):
        prepare(tmp_path)


def test_artifacts_preserve_failed_run_and_redact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("logs/scenarios/failure").mkdir(parents=True)
    Path("logs/scenarios/failure/patron.log").write_text("FAILED token=secret-value")
    Path("logs/unsafe.log").symlink_to("scenarios/failure/patron.log")
    collect_artifacts(Path("artifacts/upload"))
    saved = Path("artifacts/upload/logs/scenarios/failure/patron.log").read_text()
    assert "FAILED" in saved and "secret-value" not in saved
    assert not Path("artifacts/upload/logs/unsafe.log").exists()
