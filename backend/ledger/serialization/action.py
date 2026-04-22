"""Serialization helpers for converting actions to and from dictionaries."""

from __future__ import annotations

import inspect
from typing import Any, cast

from backend.core.enums import ActionSecurityRisk
from backend.core.errors import LLMMalformedActionError
from backend.ledger.action.action import Action
from backend.ledger.action.agent import (
    AgentRejectAction,
    AgentThinkAction,
    BlackboardAction,
    ChangeAgentStateAction,
    ClarificationRequestAction,
    CondensationAction,
    CondensationRequestAction,
    DelegateTaskAction,
    EscalateToHumanAction,
    PlaybookFinishAction,
    ProposalAction,
    RecallAction,
    TaskTrackingAction,
    UncertaintyAction,
)
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.action.code_nav import LspQueryAction
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.empty import NullAction
from backend.ledger.action.files import (
    FileEditAction,
    FileReadAction,
    FileWriteAction,
)
from backend.ledger.action.mcp import MCPAction
from backend.ledger.action.message import (
    MessageAction,
    StreamingChunkAction,
    SystemMessageAction,
)
from backend.ledger.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)

actions = (
    NullAction,
    CmdRunAction,
    FileReadAction,
    FileWriteAction,
    FileEditAction,
    AgentThinkAction,
    PlaybookFinishAction,
    AgentRejectAction,
    RecallAction,
    ChangeAgentStateAction,
    MessageAction,
    StreamingChunkAction,  # ⚡ CRITICAL: Register streaming chunks for real-time LLM responses!
    SystemMessageAction,
    CondensationAction,
    CondensationRequestAction,
    MCPAction,
    TaskTrackingAction,
    UncertaintyAction,
    ProposalAction,
    ClarificationRequestAction,
    EscalateToHumanAction,
    DelegateTaskAction,
    BlackboardAction,
    LspQueryAction,
    BrowserToolAction,
    TerminalRunAction,
    TerminalInputAction,
    TerminalReadAction,
)
ACTION_TYPE_TO_CLASS = {action_class.action: action_class for action_class in actions}


def _validate_action_dict(action: object) -> dict[str, Any]:
    """Validate that action dict is valid and has required keys."""
    if not isinstance(action, dict):
        msg = 'action must be a dictionary'
        raise LLMMalformedActionError(msg)
    if 'action' not in action:
        msg = f"'action' key is not found in action={action!r}"
        raise LLMMalformedActionError(msg)
    if not isinstance(action['action'], str):
        msg = (
            f"'action['action']={action['action']!r}' is not defined. "
            f'Available actions: {list(ACTION_TYPE_TO_CLASS.keys())}'
        )
        raise LLMMalformedActionError(msg)
    return cast(dict[str, Any], action)


def _get_action_class(action_type: str):
    """Get action class from action type."""
    action_class = ACTION_TYPE_TO_CLASS.get(action_type)
    if action_class is None:
        msg = f"'action['action']={action_type!r}' is not defined. Available actions: {list(ACTION_TYPE_TO_CLASS.keys())}"
        raise LLMMalformedActionError(msg)
    return action_class


def _process_action_args(args: dict) -> tuple[dict, str | None]:
    """Process and normalize action arguments."""
    timestamp = args.pop('timestamp', None)
    is_confirmed = args.pop('is_confirmed', None)
    if is_confirmed is not None:
        args['confirmation_state'] = is_confirmed
    _normalize_security_risk(args)
    return args, timestamp


def _normalize_security_risk(args: dict) -> None:
    """Normalize security_risk argument."""
    if 'security_risk' in args and args['security_risk'] is not None:
        try:
            args['security_risk'] = ActionSecurityRisk(args['security_risk'])
        except (ValueError, TypeError):
            args.pop('security_risk')


def _create_action_instance(
    action_class: type[Action],
    args: dict[str, Any],
    action: dict[str, Any],
    timestamp: str | None,
) -> Action:
    """Create action instance with timeout and timestamp if specified."""
    # Prune arguments that aren't in the constructor's signature to avoid TypeErrors.
    # This is needed because some Action fields (like confirmation_state) or
    # normalized arguments (like security_risk) are not accepted by all
    # action class constructors.
    sig = inspect.signature(action_class)
    constructor_args = {}
    extra_args = {}
    for k, v in args.items():
        if k in sig.parameters:
            constructor_args[k] = v
        else:
            extra_args[k] = v

    try:
        decoded_action = action_class(**constructor_args)

        # Manually set fields that weren't in the constructor but are on the instance.
        for k, v in extra_args.items():
            if hasattr(decoded_action, k):
                setattr(decoded_action, k, v)

        if 'timeout' in action:
            blocking = constructor_args.get('blocking', False)
            decoded_action.set_hard_timeout(action['timeout'], blocking=blocking)
        if timestamp:
            decoded_action._timestamp = timestamp
        return decoded_action
    except TypeError as e:
        msg = f'action={action} has the wrong arguments: {e!s}'
        raise LLMMalformedActionError(msg) from e


def action_from_dict(action: dict) -> Action:
    """Deserialize action from dictionary representation."""
    action = _validate_action_dict(action).copy()
    action_class = _get_action_class(action['action'])
    args = action.get('args', {})
    args, timestamp = _process_action_args(args)
    return _create_action_instance(action_class, args, action, timestamp)
