"""Tests for backend.cli.confirmation."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rich.console import Console

from backend.cli.confirmation import (
    ConfirmationDecision,
    _action_label,
    _confirmation_frame_style,
    _file_label,
    _risk_label,
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
        assert label.startswith('shell:')
        assert 'git status' in label

    def test_cmd_run_truncated(self) -> None:
        action = CmdRunAction(command='x' * 100)
        label = _action_label(action)
        assert '…' in label
        assert len(label) <= 100

    def test_file_edit(self) -> None:
        action = FileEditAction(path='/some/file.py', command='edit', new_str='code')
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
        action = FileEditAction(path='/foo/bar.py', command='edit', new_str='x')
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
        with patch('rich.prompt.Prompt.ask', return_value='y'):
            result = render_confirmation(console, action)
        assert result.approved is True
        assert result.remember is False

    def test_returns_false_on_reject(self) -> None:
        console = _quiet_console()
        action = CmdRunAction(command='rm -rf /')
        action.security_risk = ActionSecurityRisk.HIGH
        with patch('rich.prompt.Prompt.ask', return_value='n'):
            result = render_confirmation(console, action)
        assert result.approved is False
        assert result.remember is False

    def test_always_choice_sets_remember(self) -> None:
        console = _quiet_console()
        action = CmdRunAction(command='pytest')
        with patch('rich.prompt.Prompt.ask', return_value='a'):
            result = render_confirmation(console, action)
        assert result.approved is True
        assert result.remember is True

    def test_shows_thought_panel(self) -> None:
        console = _quiet_console()
        action = CmdRunAction(command='pip install x')
        action.thought = 'Installing required library'
        with patch('rich.prompt.Prompt.ask', return_value='y'):
            result = render_confirmation(console, action)
        assert result.approved is True

    def test_file_edit_action(self) -> None:
        console = _quiet_console()
        action = FileEditAction(path='/etc/hosts', command='edit', new_str='x')
        action.security_risk = ActionSecurityRisk.MEDIUM
        with patch('rich.prompt.Prompt.ask', return_value='n'):
            result = render_confirmation(console, action)
        assert result.approved is False

    def test_file_write_action(self) -> None:
        console = _quiet_console()
        action = FileWriteAction(path='/tmp/test.txt', content='hello')
        with patch('rich.prompt.Prompt.ask', return_value='y'):
            result = render_confirmation(console, action)
        assert result.approved is True

    def test_dont_ask_again_for_low_risk(self) -> None:
        console = _quiet_console()
        action = CmdRunAction(command='echo hello')
        action.security_risk = ActionSecurityRisk.LOW
        with patch('rich.prompt.Prompt.ask', return_value='d'):
            result = render_confirmation(console, action)
        assert result.approved is True
        assert result.remember is False
        assert result.suppress_low_risk is True

    def test_low_risk_approve_once(self) -> None:
        console = _quiet_console()
        action = CmdRunAction(command='echo hello')
        action.security_risk = ActionSecurityRisk.LOW
        with patch('rich.prompt.Prompt.ask', return_value='y'):
            result = render_confirmation(console, action)
        assert result.approved is True
        assert result.suppress_low_risk is False

    def test_low_risk_reject(self) -> None:
        console = _quiet_console()
        action = CmdRunAction(command='echo hello')
        action.security_risk = ActionSecurityRisk.LOW
        with patch('rich.prompt.Prompt.ask', return_value='n'):
            result = render_confirmation(console, action)
        assert result.approved is False
        assert result.suppress_low_risk is False

    def test_low_risk_always_allow(self) -> None:
        console = _quiet_console()
        action = CmdRunAction(command='echo hello')
        action.security_risk = ActionSecurityRisk.LOW
        with patch('rich.prompt.Prompt.ask', return_value='a'):
            result = render_confirmation(console, action)
        assert result.approved is True
        assert result.remember is True
        assert result.suppress_low_risk is False

    def test_non_low_risk_has_no_d_choice(self) -> None:
        """Choices for non-LOW risk should not include 'd'."""
        console = _quiet_console()
        action = CmdRunAction(command='sudo something')
        action.security_risk = ActionSecurityRisk.MEDIUM
        with patch('rich.prompt.Prompt.ask') as mock:
            mock.return_value = 'n'
            render_confirmation(console, action)
        _call_choices = mock.call_args[1].get('choices', [])
        assert 'd' not in _call_choices


# ---------------------------------------------------------------------------
# ConfirmationDecision
# ---------------------------------------------------------------------------


class TestConfirmationDecision:
    def test_default_suppress_low_risk_is_false(self) -> None:
        d = ConfirmationDecision(approved=True)
        assert d.suppress_low_risk is False

    def test_suppress_low_risk_true(self) -> None:
        d = ConfirmationDecision(approved=True, suppress_low_risk=True)
        assert d.suppress_low_risk is True

    def test_frozen_dataclass(self) -> None:
        d = ConfirmationDecision(approved=False)
        with pytest.raises(AttributeError):
            d.approved = True  # type: ignore[misc]
