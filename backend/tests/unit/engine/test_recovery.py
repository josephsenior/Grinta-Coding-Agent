"""Tests for backend.engine.orchestrator_helpers.recovery.

Regression coverage for the parallel-batch handling:
  - per-action errors (e.g. CONTENT_APPEARS_SERIALIZED on one of N parallel
    calls) must NOT clear sibling queued actions.
  - whole-batch shape errors (default) still clear the queue.
"""

from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock

from backend.core.errors import FunctionCallValidationError
from backend.engine.orchestrator_helpers.recovery import (
    _astep_handle_recoverable_tool_call_shape_error,
)
from backend.ledger.action.agent import AgentThinkAction, SystemHintAction


def _make_orchestrator():
    orch = MagicMock()
    orch.pending_actions = deque(
        [AgentThinkAction(thought='a'), AgentThinkAction(thought='b')]
    )
    orch.deferred_actions = deque([AgentThinkAction(thought='c')])
    orch._recoverable_tool_error_signature = ''
    orch._recoverable_tool_error_count = 0
    return orch


def test_per_action_error_preserves_sibling_actions():
    """Per-action errors (serialized content in one of N parallel calls)
    must NOT clear the pending queue. Otherwise one bad call in a batch
    silently loses every other sibling intent."""
    orch = _make_orchestrator()
    err = FunctionCallValidationError('CONTENT_APPEARS_SERIALIZED: ...', per_action=True)

    action = _astep_handle_recoverable_tool_call_shape_error(orch, err)

    assert isinstance(action, SystemHintAction)
    assert len(orch.pending_actions) == 2
    assert len(orch.deferred_actions) == 1


def test_whole_batch_error_clears_queue():
    """A non-per-action validation error (default) still clears the
    queue, matching the pre-existing stuck-recovery behavior."""
    orch = _make_orchestrator()
    err = FunctionCallValidationError('unrecognized function name')

    _astep_handle_recoverable_tool_call_shape_error(orch, err)

    assert len(orch.pending_actions) == 0
    assert len(orch.deferred_actions) == 0


def test_repeated_per_action_error_still_increments_counter():
    """The escalation counter must still fire when the same per-action
    error repeats, so a permanently bad call (e.g. agent stuck emitting
    serialized content) eventually surfaces a strategy-change prompt."""
    orch = _make_orchestrator()
    err = FunctionCallValidationError('CONTENT_APPEARS_SERIALIZED: ...', per_action=True)

    _astep_handle_recoverable_tool_call_shape_error(orch, err)
    _astep_handle_recoverable_tool_call_shape_error(orch, err)
    _astep_handle_recoverable_tool_call_shape_error(orch, err)

    # Threshold is 3 by default; the third call should escalate.
    assert orch._recoverable_tool_error_count == 3
    assert len(orch.pending_actions) == 2  # still preserved on every per-action call
