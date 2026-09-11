"""Bounded, offline planner recommendations. No execution dependencies belong here."""
from __future__ import annotations

from copy import deepcopy
import json
import math
from typing import Protocol

from .planner import RulePlanner
from .policy import validate_plan


class CandidatePlanner(Protocol):
    def plan(self, context: dict) -> dict: ...


class FakeCandidate:
    def __init__(self, mode: str = "mirror"):
        if mode not in {"mirror", "escalate", "malformed"}:
            raise ValueError("unknown fake candidate mode")
        self.mode = mode

    def plan(self, context: dict) -> dict:
        if self.mode == "mirror":
            return RulePlanner().plan(context)
        if self.mode == "malformed":
            return {"decision": ["restart_container"], "reason": "invalid fake output", "confidence": 1}
        return {"decision": "escalate", "reason": "fake candidate requests operator review", "confidence": 1.0}


def evaluate_candidate(candidate: CandidatePlanner, context: dict) -> dict:
    try:
        plan = candidate.plan(deepcopy(context))
        if not isinstance(plan, dict) or set(plan) != {"decision", "reason", "confidence"}:
            raise ValueError("plan must contain exactly decision, reason, confidence")
        if not isinstance(plan["decision"], str) or not 0 < len(plan["decision"]) <= 100:
            raise ValueError("decision must be a bounded string")
        if not isinstance(plan["reason"], str) or not 0 < len(plan["reason"]) <= 2000:
            raise ValueError("reason must be a bounded string")
        confidence = plan["confidence"]
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("confidence must be finite and between 0 and 1")
        if len(json.dumps(plan, allow_nan=False).encode()) > 12000:
            raise ValueError("plan exceeds byte limit")
        policy = validate_plan(plan, context).to_dict()
        return {"schema_valid": True, "plan": deepcopy(plan), "policy": policy, "error": None}
    except Exception as exc:
        return {"schema_valid": False, "plan": None,
                "policy": {"allowed": False, "reason": "malformed candidate output"},
                "error": f"{type(exc).__name__}: {str(exc)[:500]}"}
