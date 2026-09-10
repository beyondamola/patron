from __future__ import annotations

from .base import Trigger, TriggerRegistry
from .bad_config import ContainerBadConfigTrigger
from .dependency_down import ContainerDependencyDownTrigger
from .disk_full import ContainerDiskFullTrigger
from .high_cpu import ContainerHighCPUTrigger
from .oom_killed import ContainerOOMKilledTrigger
from .restart_loop import ContainerRestartLoopTrigger
from .stopped import ContainerStoppedTrigger
from .unhealthy import ContainerUnhealthyTrigger


def default_trigger_registry(restart_loop_threshold: int = 3) -> TriggerRegistry:
    registry = TriggerRegistry()
    registry.register(ContainerOOMKilledTrigger())
    registry.register(ContainerRestartLoopTrigger(restart_loop_threshold))
    registry.register(ContainerBadConfigTrigger())
    registry.register(ContainerDependencyDownTrigger())
    registry.register(ContainerDiskFullTrigger())
    registry.register(ContainerHighCPUTrigger())
    registry.register(ContainerUnhealthyTrigger())
    registry.register(ContainerStoppedTrigger())
    return registry


__all__ = [
    "ContainerRestartLoopTrigger",
    "ContainerOOMKilledTrigger",
    "ContainerHighCPUTrigger",
    "ContainerDiskFullTrigger",
    "ContainerBadConfigTrigger",
    "ContainerDependencyDownTrigger",
    "ContainerStoppedTrigger",
    "ContainerUnhealthyTrigger",
    "Trigger",
    "TriggerRegistry",
    "default_trigger_registry",
]
