"""Parity tests for backend/frontend agent enums."""

from __future__ import annotations

import re
from pathlib import Path

from backend.core.agent_contract import build_agent_contract


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


def _backend_contract_enums() -> dict[str, dict[str, str]]:
    return build_agent_contract()["enums"]


class TestFrontendAgentEnumParity:
    def test_agent_state_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "AgentState") == _backend_contract_enums()[
            "AgentState"
        ]

    def test_action_type_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "ActionType") == _backend_contract_enums()[
            "ActionType"
        ]

    def test_observation_type_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "ObservationType") == _backend_contract_enums()[
            "ObservationType"
        ]

    def test_action_security_risk_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "ActionSecurityRisk") == _backend_contract_enums()[
            "ActionSecurityRisk"
        ]

    def test_error_severity_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "ErrorSeverity") == _backend_contract_enums()[
            "ErrorSeverity"
        ]

    def test_error_category_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "ErrorCategory") == _backend_contract_enums()[
            "ErrorCategory"
        ]

    def test_runtime_status_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "RuntimeStatus") == _backend_contract_enums()[
            "RuntimeStatus"
        ]

    def test_action_confirmation_status_enum_matches_backend(self):
        source = _frontend_agent_types_source()
        assert _parse_ts_enum_members(source, "ActionConfirmationStatus") == _backend_contract_enums()[
            "ActionConfirmationStatus"
        ]

    def test_backend_contract_surface_is_json_serializable_and_explicit(self):
        contract = build_agent_contract()
        assert sorted(contract) == ["enums"]
        assert sorted(contract["enums"]) == [
            "ActionConfirmationStatus",
            "ActionSecurityRisk",
            "ActionType",
            "AgentState",
            "ErrorCategory",
            "ErrorSeverity",
            "ObservationType",
            "RuntimeStatus",
        ]
