"""Tests for optional security_risk under full autonomy."""

from __future__ import annotations

import pytest

from backend.core.autonomy import (
    AutonomyLevel,
    security_risk_required_for_autonomy,
)
from backend.core.errors import FunctionCallValidationError
from backend.engine.function_calling.helpers import (
    security_risk_validation_scope,
    validate_security_risk,
)
from backend.engine.prompts.section_renderers._security import _render_security
from backend.engine.tools._tool_handlers import _handle_cmd_run_tool
from backend.engine.tools.param_defs import relax_security_risk_in_tools
from backend.engine.tools.terminal import create_terminal_tool


def create_cmd_run_tool():
    return {
        'type': 'function',
        'function': {
            'name': 'cmd_run',
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {'type': 'string'},
                    'security_risk': {'type': 'string'},
                },
                'required': ['command', 'security_risk'],
            },
        },
    }


def test_security_risk_required_for_autonomy_by_level():
    assert security_risk_required_for_autonomy(AutonomyLevel.CONSERVATIVE.value)
    assert security_risk_required_for_autonomy(AutonomyLevel.BALANCED.value)
    assert not security_risk_required_for_autonomy(AutonomyLevel.FULL.value)


def test_validate_security_risk_optional_in_full_autonomy_scope():
    with security_risk_validation_scope(required=False):
        validate_security_risk({'command': 'ls'}, 'terminal')


def test_validate_security_risk_still_rejects_invalid_when_optional():
    with security_risk_validation_scope(required=False):
        with pytest.raises(FunctionCallValidationError, match='security_risk'):
            validate_security_risk(
                {'command': 'ls', 'security_risk': 'CRITICAL'},
                'terminal',
            )


def test_handle_cmd_run_without_security_risk_in_full_autonomy():
    with security_risk_validation_scope(required=False):
        action = _handle_cmd_run_tool({'command': 'echo hi'})
    assert action.command == 'echo hi'


def test_relax_security_risk_in_tools_for_full_autonomy():
    tools = [create_cmd_run_tool(), create_terminal_tool()]
    relaxed = relax_security_risk_in_tools(tools, AutonomyLevel.FULL.value)

    shell_required = relaxed[0]['function']['parameters']['required']
    assert 'command' in shell_required
    assert 'security_risk' not in shell_required

    terminal_allof = relaxed[1]['function']['parameters']['allOf']
    open_clause = next(
        clause
        for clause in terminal_allof
        if clause.get('if', {}).get('properties', {}).get('action', {}).get('const')
        == 'open'
    )
    assert 'security_risk' not in open_clause['then']['required']


def test_render_security_prompt_optional_for_full_autonomy():
    text = _render_security(autonomy_level=AutonomyLevel.FULL.value)
    assert 'optional' in text.lower()
    assert '**required**' not in text


def test_render_security_prompt_required_for_balanced_autonomy():
    text = _render_security(autonomy_level=AutonomyLevel.BALANCED.value)
    assert '**required**' in text


def test_render_security_prompt_background_server_followup():
    text = _render_security(autonomy_level=AutonomyLevel.FULL.value)
    assert 'is_background=true' in text
    assert 'terminal' in text
    assert '`wait`' in text

