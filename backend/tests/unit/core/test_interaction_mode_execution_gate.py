"""Execution-time interaction mode enforcement."""

from __future__ import annotations

from backend.core.interaction_modes import (
    AGENT_MODE,
    CHAT_MODE,
    PLAN_MODE,
    action_blocked_for_interaction_mode,
)
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.files import FileEditAction
from backend.ledger.action.agent import TaskTrackingAction
from backend.ledger.action.memory_tools import CheckpointAction, WorkingMemoryAction


def test_chat_mode_blocks_file_edit() -> None:
    action = FileEditAction(path='a.py', command='create_file', file_text='x')
    message = action_blocked_for_interaction_mode(action, CHAT_MODE)
    assert message is not None
    assert 'not allowed' in message.lower()


def test_plan_mode_allows_task_tracker() -> None:
    action = TaskTrackingAction(task_list=[])
    assert action_blocked_for_interaction_mode(action, PLAN_MODE) is None


def test_plan_mode_blocks_shell() -> None:
    action = CmdRunAction(command='echo hi')
    message = action_blocked_for_interaction_mode(action, PLAN_MODE)
    assert message is not None


def test_agent_mode_allows_shell() -> None:
    action = CmdRunAction(command='echo hi')
    assert action_blocked_for_interaction_mode(action, AGENT_MODE) is None


def test_plan_mode_blocks_checkpoint() -> None:
    action = CheckpointAction(command='save', label='snap')
    message = action_blocked_for_interaction_mode(action, PLAN_MODE)
    assert message is not None


def test_chat_mode_blocks_working_memory_write() -> None:
    action = WorkingMemoryAction(command='set', section='notes', content='x')
    message = action_blocked_for_interaction_mode(action, CHAT_MODE)
    assert message is not None
