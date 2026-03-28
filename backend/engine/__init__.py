"""Agents that edit code through tool-augmented execution."""

from backend.orchestration.agent import Agent
from backend.engine.contracts import (
    ExecutorProtocol as ExecutorProtocol,
    MemoryManagerProtocol as MemoryManagerProtocol,
    PlannerProtocol as PlannerProtocol,
    SafetyManagerProtocol as SafetyManagerProtocol,
)
from backend.engine.orchestrator import Orchestrator

Agent.register("Orchestrator", Orchestrator)

