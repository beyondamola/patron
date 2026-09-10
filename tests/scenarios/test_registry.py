from scenarios.registry import default_registry


def test_default_registry_contains_builtin_scenarios() -> None:
    registry = default_registry()

    assert registry.names() == [
        "bad_config",
        "dependency_down",
        "disk_full",
        "high_cpu",
        "oom_killed",
        "restart_loop",
        "stopped",
        "unhealthy",
    ]
    assert registry.get("stopped").description
    assert registry.get("stopped").default_target == "patron-sim-stopped"
    assert registry.get("unhealthy").default_target == "patron-sim-unhealthy"
    assert registry.get("restart_loop").default_target == "patron-sim-restart-loop"
    assert registry.get("oom_killed").default_target == "patron-sim-oom-killed"
    assert registry.get("dependency_down").default_target == "patron-sim-dependency-app"
