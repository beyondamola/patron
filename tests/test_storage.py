import json
from unittest.mock import Mock

import pytest

from harness.incident import ESCALATED, IncidentRegistry
from harness.runtime import PatronRuntime
from harness.storage import StateConflict, StateLock, atomic_json


def test_lock_reentrant_but_rejects_other_owner(tmp_path):
    path = tmp_path / "state.json"
    first, second = StateLock(path), StateLock(path)
    with first.acquire():
        with first.acquire():
            with pytest.raises(StateConflict):
                with second.acquire():
                    pytest.fail("second writer acquired lock")
    with second.acquire():
        pass


def test_stale_lock_file_is_not_ownership(tmp_path):
    path = tmp_path / "state.json"
    path.with_name("state.json.lock").write_text("12345")
    with StateLock(path).acquire():
        pass


def test_atomic_replace_failure_preserves_original(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    atomic_json(path, {"value": 1})
    def fail(*args):
        raise OSError("injected replace failure")
    monkeypatch.setattr("harness.storage.os.replace", fail)
    with pytest.raises(OSError):
        atomic_json(path, {"value": 2})
    assert json.loads(path.read_text()) == {"value": 1}
    assert list(tmp_path.iterdir()) == [path]


def test_legacy_migration_preserves_backup_and_suppression(tmp_path):
    path = tmp_path / "state.json"
    registry = IncidentRegistry(path)
    incident, _ = registry.get_or_open("x", "docker_container", "X", "failure")
    registry.mark_final(incident, ESCALATED)
    legacy = json.dumps({"incidents": {"x": incident.to_dict()}, "resolved_at": registry.resolved_at})
    path.write_text(legacy)
    migrated = IncidentRegistry(path)
    assert not path.with_name("state.json.v0.bak").exists()
    migrated.persist()
    assert path.with_name("state.json.v0.bak").read_text() == legacy
    assert json.loads(path.read_text())["schema_version"] == 1
    assert IncidentRegistry(path).get_or_open("x", "docker_container", "X", "failure") == (None, False)


def test_stale_registry_cannot_overwrite_state(tmp_path):
    path = tmp_path / "state.json"
    first, stale = IncidentRegistry(path), IncidentRegistry(path)
    first.persist()
    with pytest.raises(StateConflict):
        stale.persist()
    assert json.loads(path.read_text())["revision"] == 1


@pytest.mark.parametrize("payload", [[], {}, {"schema_version": 999},
    {"schema_version": 1, "revision": -1, "incidents": {}, "resolved_at": {}}])
def test_invalid_state_fails_without_mutation(tmp_path, payload):
    path = tmp_path / "state.json"
    original = json.dumps(payload)
    path.write_text(original)
    with pytest.raises(ValueError):
        IncidentRegistry(path)
    assert path.read_text() == original


def test_explicit_state_path_overrides_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRON_STATE_PATH", str(tmp_path / "environment.json"))
    assert IncidentRegistry(tmp_path / "explicit.json").state_path.name == "explicit.json"
    assert IncidentRegistry().state_path.name == "environment.json"


def test_runtime_checks_ownership_before_collection(tmp_path):
    path = tmp_path / "state.json"
    collector = Mock()
    runtime = PatronRuntime(registry=IncidentRegistry(path), collector=collector)
    with StateLock(path).acquire():
        with pytest.raises(StateConflict):
            runtime.process_once()
    collector.collect.assert_not_called()


def test_runtime_checks_revision_before_collection(tmp_path):
    path = tmp_path / "state.json"
    collector = Mock()
    runtime = PatronRuntime(registry=IncidentRegistry(path), collector=collector)
    IncidentRegistry(path).persist()
    with pytest.raises(StateConflict):
        runtime.process_once()
    collector.collect.assert_not_called()


def test_migration_never_overwrites_existing_backup(tmp_path):
    path = tmp_path / "state.json"
    original = '{"incidents": {}, "resolved_at": {}}'
    path.write_text(original)
    backup = path.with_name("state.json.v0.bak")
    backup.write_text("previous migration")
    with pytest.raises(StateConflict, match="backup"):
        IncidentRegistry(path).persist()
    assert path.read_text() == original
    assert backup.read_text() == "previous migration"


def test_failed_file_sync_leaves_state_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    atomic_json(path, {"value": 1})
    def fail(*args):
        raise OSError("injected fsync failure")
    monkeypatch.setattr("harness.storage.os.fsync", fail)
    with pytest.raises(OSError):
        atomic_json(path, {"value": 2})
    assert json.loads(path.read_text()) == {"value": 1}


def test_newly_unsupported_schema_rejected_before_collection(tmp_path):
    path = tmp_path / "state.json"
    collector = Mock()
    runtime = PatronRuntime(registry=IncidentRegistry(path), collector=collector)
    path.write_text('{"schema_version": 999, "revision": 0}')
    with pytest.raises(ValueError, match="schema"):
        runtime.process_once()
    collector.collect.assert_not_called()


def test_exclusive_publication_never_overwrites(tmp_path):
    path = tmp_path / "request.json"
    atomic_json(path, {"request": "first"}, replace_existing=False)
    with pytest.raises(FileExistsError):
        atomic_json(path, {"request": "second"}, replace_existing=False)
    assert json.loads(path.read_text()) == {"request": "first"}
    assert list(tmp_path.iterdir()) == [path]
