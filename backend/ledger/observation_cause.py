"""Normalize observation ``cause`` to the originating action's stream id.

Tool/runtime observations must use the same integer id as ``Action.id`` after the
action is added to the event stream so :class:`ObservationService` can match
pending actions reliably (avoids str/int drift from serialization).
"""

from __future__ import annotations

import contextlib
from typing import Any

from backend.core.logger import app_logger as logger
from backend.ledger.event import Event


def attach_observation_cause(
    observation: Any,
    action_or_id: Any,
    *,
    context: str = '',
) -> None:
    """Set ``observation.cause`` from an :class:`Action` or explicit stream id.

    * ``action_or_id is None`` clears ``cause`` (observations not tied to a tool).
    * Invalid or unassigned ids (:data:`Event.INVALID_ID`) log a warning and clear.
    """
    if (
        action_or_id is not None
        and not isinstance(action_or_id, int)
        and getattr(observation, 'tool_call_metadata', None) is None
    ):
        tcm = getattr(action_or_id, 'tool_call_metadata', None)
        if tcm is not None:
            observation.tool_call_metadata = tcm

    if action_or_id is None:
        observation.cause = None
        return

    raw_id = (
        getattr(action_or_id, 'id', None)
        if not isinstance(action_or_id, int)
        else action_or_id
    )
    if raw_id is None:
        observation.cause = None
        return

    with contextlib.suppress(TypeError, ValueError):
        nid = int(raw_id)
        if nid != Event.INVALID_ID:
            observation.cause = nid
            return

    suffix = f' ({context})' if context else ''
    logger.warning(
        'attach_observation_cause: invalid action id %r%s; leaving cause unset',
        raw_id,
        suffix,
    )
    observation.cause = None
