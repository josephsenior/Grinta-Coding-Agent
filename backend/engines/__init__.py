"""Collection of core agent implementations for Forge."""

# Import submodules using relative imports to avoid circular dependencies
from backend.controller.agent import Agent

from . import (
    auditor,
    echo,
    locator,
    navigator,
    orchestrator,
)

__all__ = [
    "Agent",
    "navigator",
    "orchestrator",
    "echo",
    "locator",
    "auditor",
]
