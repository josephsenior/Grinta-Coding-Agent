"""Tests for microcompact tool-output shedding."""

from __future__ import annotations

import pytest

from backend.context.compactor.strategies.microcompact_compactor import (
    MicrocompactCompactor,
)
from backend.context.tool_result_storage import TOOL_RESULT_CLEARED_MESSAGE
from backend.context.view import View
from backend.ledger.action import MessageAction
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.files import FileReadObservation


def _event(eid: int, content: str = '') -> MessageAction:
    event = MessageAction(content=content or f'msg-{eid}')
    event._id = eid
    return event


@pytest.mark.asyncio
async def test_microcompact_clears_old_tool_outputs_only():
    events = [
        _event(1),
        CmdOutputObservation(content='old output ' * 100, command='pytest'),
        FileReadObservation(path='a.py', content='print(1)\n' * 50),
        ErrorObservation(content='recent failure'),
        _event(5),
        CmdOutputObservation(content='recent output', command='pytest'),
    ]
    compactor = MicrocompactCompactor(preserve_recent=2)
    result = await compactor.compact(View(events=events))

    assert isinstance(result, View)
    assert result[1].content == TOOL_RESULT_CLEARED_MESSAGE
    assert result[2].content == TOOL_RESULT_CLEARED_MESSAGE
    assert result[3].content == 'recent failure'
    assert 'recent output' in str(result[5].content)
