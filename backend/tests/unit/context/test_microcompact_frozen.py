"""Tests for frozen microcompact tool-output shedding."""

from __future__ import annotations

from backend.context.compactor.microcompact import (
    MICROCOMPACT_CLEARED_IDS_KEY,
    apply_microcompact,
    clear_microcompact_cleared_ids,
    get_microcompact_cleared_ids,
)
from backend.context.tool_result_storage import TOOL_RESULT_CLEARED_MESSAGE
from backend.ledger.action import MessageAction
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.files import FileReadObservation


class _State:
    def __init__(self) -> None:
        self.extra_data: dict[str, object] = {}

    def set_extra(self, key: str, value: object, *, source: str = '') -> None:
        self.extra_data[key] = value


def _msg(eid: int, content: str = '') -> MessageAction:
    event = MessageAction(content=content or f'msg-{eid}')
    event._id = eid
    return event


def test_microcompact_records_cleared_ids_in_state():
    state = _State()
    old_cmd = CmdOutputObservation(content='old output ' * 100, command='pytest')
    old_cmd._id = 2
    old_read = FileReadObservation(path='a.py', content='print(1)\n' * 50)
    old_read._id = 3
    recent_cmd = CmdOutputObservation(content='recent output', command='pytest')
    recent_cmd._id = 6
    events = [
        _msg(1),
        old_cmd,
        old_read,
        _msg(5),
        recent_cmd,
    ]
    result = apply_microcompact(events, preserve_recent=2, state=state)

    assert result[1].content == TOOL_RESULT_CLEARED_MESSAGE
    assert result[2].content == TOOL_RESULT_CLEARED_MESSAGE
    assert 'recent output' in str(result[4].content)
    assert get_microcompact_cleared_ids(state) == {2, 3}


def test_microcompact_reapplies_frozen_clears_when_event_regains_full_content():
    state = _State()
    state.extra_data[MICROCOMPACT_CLEARED_IDS_KEY] = [2]
    events = [
        _msg(1),
        CmdOutputObservation(content='restored full body ' * 50, command='pytest'),
        _msg(3),
    ]

    result = apply_microcompact(events, preserve_recent=1, state=state)

    assert result[1].content == TOOL_RESULT_CLEARED_MESSAGE
    assert get_microcompact_cleared_ids(state) == {2}


def test_microcompact_only_adds_newly_aged_events_to_frozen_set():
    state = _State()
    first_obs = CmdOutputObservation(content='x' * 300, command='a')
    first_obs._id = 2
    events = [_msg(1), first_obs]

    apply_microcompact(events, preserve_recent=1, state=state)
    assert get_microcompact_cleared_ids(state) == set()

    events.append(_msg(3))
    second_obs = CmdOutputObservation(content='y' * 300, command='b')
    second_obs._id = 4
    events.append(second_obs)

    apply_microcompact(events, preserve_recent=1, state=state)
    assert get_microcompact_cleared_ids(state) == {2}


def test_microcompact_preserves_errors_outside_window():
    state = _State()
    err = ErrorObservation(content='old failure')
    err._id = 1
    old_cmd = CmdOutputObservation(content='old output', command='pytest')
    old_cmd._id = 2
    recent = _msg(3)
    events = [err, old_cmd, recent]

    result = apply_microcompact(events, preserve_recent=1, state=state)

    assert result[0].content == 'old failure'
    assert result[1].content == TOOL_RESULT_CLEARED_MESSAGE
    assert get_microcompact_cleared_ids(state) == {2}


def test_clear_microcompact_cleared_ids():
    state = _State()
    state.extra_data[MICROCOMPACT_CLEARED_IDS_KEY] = [1, 2, 3]

    clear_microcompact_cleared_ids(state)

    assert get_microcompact_cleared_ids(state) == set()
    assert state.extra_data[MICROCOMPACT_CLEARED_IDS_KEY] == []
