"""Backend-owned agent/frontend contract surface.

Keep this module intentionally small and explicit: it defines the curated
agent-facing enum surface the frontend is allowed to mirror.
"""

from __future__ import annotations

from typing import Any

from backend.core.enums import (
    ActionConfirmationStatus,
    ActionSecurityRisk,
    ActionType,
    AgentState,
    ErrorCategory,
    ErrorSeverity,
    ObservationType,
    RuntimeStatus,
)


def _enum_members(enum_cls) -> dict[str, Any]:
    return {
        item.name: str(item.value) if isinstance(item.value, int) else item.value
        for item in enum_cls
    }


def build_agent_contract() -> dict[str, dict[str, dict[str, Any]]]:
    """Return the curated backend-owned contract shared with the frontend."""
    return {
        'enums': {
            'AgentState': _enum_members(AgentState),
            'ActionType': _enum_members(ActionType),
            'ObservationType': _enum_members(ObservationType),
            'ActionSecurityRisk': _enum_members(ActionSecurityRisk),
            'ErrorSeverity': _enum_members(ErrorSeverity),
            'ErrorCategory': _enum_members(ErrorCategory),
            'RuntimeStatus': _enum_members(RuntimeStatus),
            'ActionConfirmationStatus': _enum_members(ActionConfirmationStatus),
        }
    }
