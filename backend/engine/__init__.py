"""Agents that edit code through tool-augmented execution."""

from backend.engine.contracts import (
    ExecutorProtocol as ExecutorProtocol,
)
from backend.engine.contracts import (
    MemoryManagerProtocol as MemoryManagerProtocol,
)
from backend.engine.contracts import (
    PlannerProtocol as PlannerProtocol,
)
from backend.engine.contracts import (
    SafetyManagerProtocol as SafetyManagerProtocol,
)
from backend.engine.orchestrator import Orchestrator
from backend.orchestration.agent import Agent

Agent.register('Orchestrator', Orchestrator)
