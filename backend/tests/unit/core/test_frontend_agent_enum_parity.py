"""Parity tests for backend/frontend agent enums."""

from __future__ import annotations

import re
from pathlib import Path

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


def _parse_ts_enum_members(source: str, enum_name: str) -> dict[str, str]:
    pattern = rf"export enum {enum_name} \{{(.*?)\n\}}"
    match = re.search(pattern, source, re.DOTALL)
    assert match is not None, f"enum {enum_name} not found"
    body = match.group(1)
    members: dict[str, str] = {}
    for raw_line in body.splitlines():
        line = raw_line.strip().rstrip(",")
        if not line:
            continue
        member_match = re.match(r'([A-Z0-9_]+)\s*=\s*(".*?"|-?\d+)', line)
        assert member_match is not None, f"Could not parse enum member line: {line}"
        name, value = member_match.groups()
        members[name] = value.strip('"')
    return members


def _frontend_agent_types_source() -> str:
    root = Path(__file__).resolve().parents[4]
    path = root / "frontend" / "src" / "types" / "agent.ts"
    return path.read_text(encoding="utf-8")


class TestFrontendAgentEnumParity:
    def test_agent_state_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "AgentState") == {
            item.name: item.value for item in AgentState
        }

    def test_action_type_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "ActionType") == {
            item.name: item.value for item in ActionType
        }

    def test_observation_type_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "ObservationType") == {
            item.name: item.value for item in ObservationType
        }

    def test_action_security_risk_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "ActionSecurityRisk") == {
            item.name: str(item.value) for item in ActionSecurityRisk
        }

    def test_error_severity_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "ErrorSeverity") == {
            item.name: item.value for item in ErrorSeverity
        }

    def test_error_category_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "ErrorCategory") == {
            item.name: item.value for item in ErrorCategory
        }

    def test_runtime_status_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "RuntimeStatus") == {
            item.name: item.value for item in RuntimeStatus
        }

    def test_action_confirmation_status_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "ActionConfirmationStatus") == {
            item.name: item.value for item in ActionConfirmationStatus
        }
