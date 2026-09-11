from harness.shadow import FakeCandidate, evaluate_candidate


def context():
    return {"resource": "target", "incident_type": "CONTAINER_STOPPED",
            "allowed_actions": ["restart_container", "escalate"]}


def test_fake_mirror_escalation_and_malformed_outputs():
    assert evaluate_candidate(FakeCandidate(), context())["plan"]["decision"] == "restart_container"
    assert evaluate_candidate(FakeCandidate("escalate"), context())["policy"]["allowed"]
    assert not evaluate_candidate(FakeCandidate("malformed"), context())["schema_valid"]


def test_mutating_candidate_cannot_change_source_context():
    class MutatingCandidate:
        def plan(self, packet):
            packet["allowed_actions"].append("delete_container")
            return {"decision": "delete_container", "reason": "unsafe", "confidence": 1}

    packet = context()
    result = evaluate_candidate(MutatingCandidate(), packet)
    assert result["schema_valid"] and not result["policy"]["allowed"]
    assert packet == context()


def test_nonfinite_confidence_and_extra_fields_fail_closed():
    from unittest.mock import Mock
    for plan in ({"decision": "restart_container", "reason": "x", "confidence": float("nan")},
                 {"decision": "restart_container", "reason": "x", "confidence": 1, "shell": "unsafe"},
                 {"decision": "restart_container", "reason": "x" * 2001, "confidence": 1}):
        result = evaluate_candidate(Mock(plan=Mock(return_value=plan)), context())
        assert not result["schema_valid"] and not result["policy"]["allowed"]
