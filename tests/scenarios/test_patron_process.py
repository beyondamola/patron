from scenarios.patron_process import ManagedPatron


def test_managed_patron_command_uses_exact_target() -> None:
    patron = ManagedPatron("patron-sim-unhealthy", "scenario-1", interval=1, trace=True)

    command = patron.command()

    assert "--target" in command
    assert "patron-sim-unhealthy" in command
    assert "--trace" in command

