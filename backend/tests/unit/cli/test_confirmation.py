"""Tests for backend.cli.confirmation."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rich.console import Console

from backend.cli.confirmation import (
    _action_label,
    _confirmation_frame_style,
    _file_label,
    _risk_label,
    build_confirmation_action,
    render_confirmation,
)
from backend.core.enums import ActionSecurityRisk, AgentState
from backend.ledger.action import (
    CmdRunAction,
    FileEditAction,
    FileWriteAction,
    MessageAction,
)


def _quiet_console() -> Console:
    return Console(quiet=True)


# ---------------------------------------------------------------------------
# _risk_label
# ---------------------------------------------------------------------------

class TestRiskLabel:
    def test_high_risk(self) -> None:
        action = CmdRunAction(command='rm -rf /')
        action.security_risk = ActionSecurityRisk.HIGH
        text, style = _risk_label(action)
        assert text == 'HIGH'

    def test_medium_risk(self) -> None:
        action = CmdRunAction(command='sudo something')
        action.security_risk = ActionSecurityRisk.MEDIUM
        text, style = _risk_label(action)
        assert text == 'MEDIUM'

    def test_low_risk(self) -> None:
        action = CmdRunAction(command='echo hello')
        action.security_risk = ActionSecurityRisk.LOW
        text, style = _risk_label(action)
        assert text == 'LOW'

    def test_unknown_risk_returns_ask(self) -> None:
        action = CmdRunAction(command='ls')
        action.security_risk = ActionSecurityRisk.UNKNOWN
        text, style = _risk_label(action)
        assert text == 'ASK'

    def test_integer_risk_value_converted(self) -> None:
        action = CmdRunAction(command='ls')
        action.security_risk = 2  # type: ignore[assignment]  # ActionSecurityRisk.HIGH
        text, _ = _risk_label(action)
        assert text == 'HIGH'

    def test_invalid_risk_value_falls_back_to_ask(self) -> None:
        action = CmdRunAction(command='ls')
        action.security_risk = 999  # type: ignore[assignment]
        text, _ = _risk_label(action)
        assert text == 'ASK'


# ---------------------------------------------------------------------------
# _action_label
# ---------------------------------------------------------------------------

class TestActionLabel:
    def test_cmd_run_short(self) -> None:
        action = CmdRunAction(command='git status')
        label = _action_label(action)
        assert label.startswith('bash:')
        assert 'git status' in label

    def test_cmd_run_truncated(self) -> None:
        action = CmdRunAction(command='x' * 100)
        label = _action_label(action)
        assert label.endswith('…')
        assert len(label) <= 90

    def test_file_edit(self) -> None:
        action = FileEditAction(path='/some/file.py', content='code')
        label = _action_label(action)
        assert label.startswith('edit:')
        assert '/some/file.py' in label

    def test_file_write(self) -> None:
        action = FileWriteAction(path='/new/file.py', content='code')
        label = _action_label(action)
        assert label.startswith('write:')
        assert '/new/file.py' in label

    def test_other_action(self) -> None:
        action = MessageAction(content='hello')
        label = _action_label(action)
        assert 'MessageAction' in label


# ---------------------------------------------------------------------------
# _file_label
# ---------------------------------------------------------------------------

class TestFileLabel:
    def test_file_edit(self) -> None:
        action = FileEditAction(path='/foo/bar.py', content='x')
        assert _file_label(action) == '/foo/bar.py'

    def test_file_write(self) -> None:
        action = FileWriteAction(path='/foo/baz.py', content='x')
        assert _file_label(action) == '/foo/baz.py'

    def test_cmd_run_returns_dash(self) -> None:
        action = CmdRunAction(command='ls')
        assert _file_label(action) == '—'

    def test_other_action_returns_dash(self) -> None:
        action = MessageAction(content='hi')
        assert _file_label(action) == '—'


# ---------------------------------------------------------------------------
# _confirmation_frame_style
# ---------------------------------------------------------------------------

class TestConfirmationFrameStyle:
    def test_high_risk(self) -> None:
        style = _confirmation_frame_style('HIGH')
        # Should not contain 'bold ' (stripped)
        assert 'bold ' not in style

    def test_medium(self) -> None:
        style = _confirmation_frame_style('MEDIUM')
        assert isinstance(style, str) and len(style) > 0

    def test_ask(self) -> None:
        style = _confirmation_frame_style('ASK')
        assert isinstance(style, str)

    def test_low(self) -> None:
        style = _confirmation_frame_style('LOW')
        assert isinstance(style, str)

    def test_fallback(self) -> None:
        style = _confirmation_frame_style('SOMETHING_ELSE')
        assert isinstance(style, str)


# ---------------------------------------------------------------------------
# render_confirmation
# ---------------------------------------------------------------------------

class TestRenderConfirmation:
    def test_returns_true_on_approve(self) -> None:
        console = _quiet_console()
        action = CmdRunAction(command='git status')
        with patch('rich.prompt.Confirm.ask', return_value=True):
            result = render_confirmation(console, action)
        assert result is True

    def test_returns_false_on_reject(self) -> None:
        console = _quiet_console()
        action = CmdRunAction(command='rm -rf /')
        action.security_risk = ActionSecurityRisk.HIGH
        with patch('rich.prompt.Confirm.ask', return_value=False):
            result = render_confirmation(console, action)
        assert result is False

    def test_shows_thought_panel(self) -> None:
        console = _quiet_console()
        action = CmdRunAction(command='pip install x')
        action.thought = 'Installing required library'
        with patch('rich.prompt.Confirm.ask', return_value=True):
            result = render_confirmation(console, action)
        assert result is True

    def test_file_edit_action(self) -> None:
        console = _quiet_console()
        action = FileEditAction(path='/etc/hosts', content='x')
        action.security_risk = ActionSecurityRisk.MEDIUM
        with patch('rich.prompt.Confirm.ask', return_value=False):
            result = render_confirmation(console, action)
        assert result is False

    def test_file_write_action(self) -> None:
        console = _quiet_console()
        action = FileWriteAction(path='/tmp/test.txt', content='hello')
        with patch('rich.prompt.Confirm.ask', return_value=True):
            result = render_confirmation(console, action)
        assert result is True


# ---------------------------------------------------------------------------
# build_confirmation_action
# ---------------------------------------------------------------------------

class TestBuildConfirmationAction:
    def test_approved(self) -> None:
        action = build_confirmation_action(approved=True)
        assert action.agent_state == AgentState.USER_CONFIRMED

    def test_rejected(self) -> None:
        action = build_confirmation_action(approved=False)
        assert action.agent_state == AgentState.USER_REJECTED
