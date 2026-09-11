from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..collector import ContainerSnapshot


class Trigger(ABC):
    incident_type: str

    @abstractmethod
    def evaluate(self, snapshot: ContainerSnapshot) -> bool:
        raise NotImplementedError

    @abstractmethod
    def build_metadata(self, snapshot: ContainerSnapshot) -> dict[str, Any]:
        raise NotImplementedError

    def build_packet(self, snapshot: ContainerSnapshot) -> dict[str, Any]:
        metadata = self.build_metadata(snapshot)
        return {
            "incident_type": self.incident_type,
            "resource": snapshot.name,
            "resource_type": "docker_container",
            "reason": metadata["reason"],
            "observed_state": metadata["observed_state"],
            "expected_state": metadata.get("expected_state", "running"),
            "metadata": metadata,
        }

    def trace(self, snapshot: ContainerSnapshot) -> dict[str, Any]:
        result = self.evaluate(snapshot)
        return {
            "incident_type": self.incident_type,
            "result": result,
            "reason": "matched" if result else "not matched",
        }


class TriggerRegistry:
    def __init__(self, triggers: list[Trigger] | None = None) -> None:
        self.triggers = triggers or []

    def register(self, trigger: Trigger) -> None:
        self.triggers.append(trigger)

    def evaluate(self, snapshot: ContainerSnapshot) -> dict[str, Any] | None:
        return self.evaluate_with_trace(snapshot)[0]

    def evaluate_with_trace(self, snapshot: ContainerSnapshot) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        traces = []
        packet = None
        for priority, trigger in enumerate(self.triggers):
            trace = trigger.trace(snapshot)
            trace["priority"] = priority
            trace["selected"] = packet is None and trace["result"]
            traces.append(trace)
            if packet is None and trace["result"]:
                packet = trigger.build_packet(snapshot)
        return packet, traces
