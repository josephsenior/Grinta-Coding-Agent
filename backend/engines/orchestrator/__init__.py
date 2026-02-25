"""Agents that edit code through tool-augmented execution."""

from backend.controller.agent import Agent
from backend.engines.orchestrator.contracts import (
    ExecutorProtocol,
    MemoryManagerProtocol,
    PlannerProtocol,
    SafetyManagerProtocol,
)
from backend.engines.orchestrator.orchestrator import Orchestrator

Agent.register("Orchestrator", Orchestrator)

