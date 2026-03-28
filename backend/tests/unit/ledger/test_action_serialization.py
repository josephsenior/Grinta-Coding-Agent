"""Tests for backend.ledger.serialization.action."""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.errors import LLMMalformedActionError
from backend.ledger.action import (
    CmdRunAction,
    MessageAction,
    NullAction,
)
from backend.ledger.serialization.action import (
    ACTION_TYPE_TO_CLASS,
    action_from_dict,
    _normalize_security_risk,
    _validate_action_dict,
)


# ── _validate_action_dict ────────────────────────────────────────────


class TestValidateActionDict:
    def test_valid(self):
        d = {"action": "message", "args": {}}
        assert _validate_action_dict(d) == d

    def test_not_a_dict(self):
        with pytest.raises(LLMMalformedActionError, match="dictionary"):
            _validate_action_dict("not a dict")

    def test_missing_action_key(self):
        with pytest.raises(LLMMalformedActionError, match="action"):
            _validate_action_dict({"args": {}})

    def test_action_not_string(self):
        with pytest.raises(LLMMalformedActionError):
            _validate_action_dict({"action": 123})


# ── _normalize_security_risk ─────────────────────────────────────────


class TestNormalizeSecurityRisk:
    def test_valid_risk_value(self):
        from backend.core.enums import ActionSecurityRisk

        # Use an actual ActionSecurityRisk member value
        valid_value = list(ActionSecurityRisk)[0].value
        args = {"security_risk": valid_value}
        _normalize_security_risk(args)
        assert args["security_risk"] == ActionSecurityRisk(valid_value)

    def test_none_risk(self):
        args = {"security_risk": None}
        _normalize_security_risk(args)
        assert args["security_risk"] is None

    def test_invalid_value_removed(self):
        args = {"security_risk": "not_a_valid_risk"}
        _normalize_security_risk(args)
        assert "security_risk" not in args

    def test_no_key(self):
        args: dict[str, Any] = {}
        _normalize_security_risk(args)
        assert "security_risk" not in args


# ── action_from_dict ─────────────────────────────────────────────────


class TestActionFromDict:
    def test_message_action(self):
        d = {
            "action": "message",
            "args": {"content": "hi", "image_urls": [], "wait_for_response": False},
        }
        evt = action_from_dict(d)
        assert isinstance(evt, MessageAction)
        assert evt.content == "hi"

    def test_null_action(self):
        d = {"action": "null", "args": {}}
        evt = action_from_dict(d)
        assert isinstance(evt, NullAction)

    def test_cmd_run_action(self):
        d = {"action": "run", "args": {"command": "echo hello"}}
        evt = action_from_dict(d)
        assert isinstance(evt, CmdRunAction)
        assert evt.command == "echo hello"

    def test_unknown_action_type(self):
        d = {"action": "nonexistent_action", "args": {}}
        with pytest.raises(LLMMalformedActionError):
            action_from_dict(d)

    def test_unknown_args_keys_are_ignored(self):
        d = {"action": "message", "args": {"invalid_key_only": True}}
        evt = action_from_dict(d)
        assert isinstance(evt, MessageAction)
        assert evt.content == ""
        assert not hasattr(evt, "invalid_key_only")

    def test_with_timeout(self):
        d = {"action": "run", "args": {"command": "ls"}, "timeout": 30}
        evt = action_from_dict(d)
        assert evt.timeout == 30

    def test_is_confirmed_remapped(self):
        """Verify that is_confirmed is removed and mapped to confirmation_state in args."""
        from backend.ledger.serialization.action import _process_action_args

        args = {"content": "x", "is_confirmed": "confirmed"}
        processed, _ = _process_action_args(args)
        assert "is_confirmed" not in processed
        assert processed["confirmation_state"] == "confirmed"


# ── ACTION_TYPE_TO_CLASS ─────────────────────────────────────────────


class TestActionTypeToClass:
    def test_has_common_actions(self):
        assert "message" in ACTION_TYPE_TO_CLASS
        assert "run" in ACTION_TYPE_TO_CLASS
        assert "null" in ACTION_TYPE_TO_CLASS
        assert "read" in ACTION_TYPE_TO_CLASS
        assert "edit" in ACTION_TYPE_TO_CLASS
