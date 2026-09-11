from scenarios.patron_process import ManagedPatron


def test_managed_patron_command_uses_exact_target() -> None:
    patron = ManagedPatron("patron-sim-unhealthy", "scenario-1", interval=1, trace=True)

    command = patron.command()

    assert "--target" in command
    assert "patron-sim-unhealthy" in command
    assert "--trace" in command
    assert command[command.index("--config") + 1] == str(patron.config_path.resolve())


def test_managed_patron_writes_exact_detector_configuration(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from harness.config import DetectorConfig

    config = DetectorConfig(cpu_threshold=85, restart_loop_threshold=4)
    patron = ManagedPatron("cpu-target", "unique", log_root=tmp_path, config=config)
    process = Mock()
    process.poll.return_value = 0
    monkeypatch.setattr("scenarios.patron_process.subprocess.Popen", Mock(return_value=process))
    try:
        patron.start()
        assert DetectorConfig.load(patron.config_path) == config
    finally:
        patron.stop()
