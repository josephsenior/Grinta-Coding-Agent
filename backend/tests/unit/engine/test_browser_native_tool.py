"""Tests for native browser tool wiring (no real Chromium)."""

import pytest

from backend.core.enums import ActionSecurityRisk
from backend.core.errors import FunctionCallValidationError
from backend.engine.function_calling import _handle_browser_tool
from backend.engine.tools.browser_native import (
    BROWSER_TOOL_NAME,
    build_browser_tool_action,
    create_browser_tool,
)
from backend.ledger.action.browser_tool import BrowserToolAction


def test_create_browser_tool_schema_name():
    tool = create_browser_tool()
    assert tool['function']['name'] == BROWSER_TOOL_NAME
    assert 'command' in tool['function']['parameters']['properties']


def test_build_browser_tool_action_navigate():
    act = build_browser_tool_action(
        {'command': 'navigate', 'url': 'https://example.com'}
    )
    assert isinstance(act, BrowserToolAction)
    assert act.command == 'navigate'
    assert act.params['url'] == 'https://example.com'
    assert act.security_risk == ActionSecurityRisk.HIGH


def test_build_browser_tool_action_start_is_medium_risk():
    act = build_browser_tool_action({'command': 'start'})
    assert act.security_risk == ActionSecurityRisk.MEDIUM


def test_build_rejects_unknown_command():
    with pytest.raises(FunctionCallValidationError):
        build_browser_tool_action({'command': 'not_a_real_command'})


def test_handle_browser_tool_wraps_security():
    act = _handle_browser_tool({'command': 'snapshot', 'security_risk': 'HIGH'})
    assert isinstance(act, BrowserToolAction)
    assert act.security_risk == ActionSecurityRisk.HIGH
