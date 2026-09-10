from harness.planner import RulePlanner


def base_context(incident_type: str) -> dict:
    return {
        "incident_type": incident_type,
        "resource": "mvp-nginx",
        "restart_count": 3,
        "health_status": "unhealthy",
    }


def test_rule_planner_restarts_stopped_container() -> None:
    plan = RulePlanner().plan(base_context("CONTAINER_STOPPED"))

    assert plan["decision"] == "restart_container"


def test_rule_planner_restarts_unhealthy_container() -> None:
    plan = RulePlanner().plan(base_context("CONTAINER_UNHEALTHY"))

    assert plan["decision"] == "restart_container"
    assert "unhealthy" in plan["reason"]


def test_rule_planner_escalates_restart_loop() -> None:
    plan = RulePlanner().plan(base_context("CONTAINER_RESTART_LOOP"))

    assert plan["decision"] == "escalate"
    assert plan["confidence"] == 0.99


def test_rule_planner_escalates_new_incident_types() -> None:
    for incident_type in [
        "CONTAINER_OOM_KILLED",
        "CONTAINER_HIGH_CPU",
        "CONTAINER_DISK_FULL",
        "CONTAINER_BAD_CONFIG",
        "CONTAINER_DEPENDENCY_DOWN",
    ]:
        plan = RulePlanner().plan(base_context(incident_type))

        assert plan["decision"] == "escalate"
