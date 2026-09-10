from harness.policy import validate_plan


def test_policy_allows_restart_container_for_incident_resource() -> None:
    context = {"resource": "mvp-nginx", "allowed_actions": ["restart_container"]}
    plan = {
        "decision": "restart_container",
        "reason": "container stopped",
        "confidence": 0.97,
    }

    decision = validate_plan(plan, context)

    assert decision.allowed


def test_policy_rejects_non_allowlisted_action() -> None:
    context = {"resource": "mvp-nginx", "allowed_actions": ["restart_container"]}
    plan = {
        "decision": "delete_container",
        "reason": "bad idea",
        "confidence": 0.97,
    }

    decision = validate_plan(plan, context)

    assert not decision.allowed
    assert "not allowlisted" in decision.reason


def test_policy_rejects_action_disallowed_by_context() -> None:
    context = {"resource": "mvp-nginx", "allowed_actions": []}
    plan = {
        "decision": "restart_container",
        "reason": "container stopped",
        "confidence": 0.97,
    }

    decision = validate_plan(plan, context)

    assert not decision.allowed


def test_policy_allows_escalate_when_context_allows_it() -> None:
    context = {"resource": "mvp-nginx", "allowed_actions": ["escalate"]}
    plan = {
        "decision": "escalate",
        "reason": "restart loop",
        "confidence": 0.99,
    }

    decision = validate_plan(plan, context)

    assert decision.allowed
