from __future__ import annotations

from collections import deque
from types import SimpleNamespace

from backend.ledger import EventSource
from backend.ledger.action import FileEditAction
from backend.ledger.observation import ErrorObservation, FileEditObservation
from backend.ledger.tool import ToolCallMetadata
from backend.orchestration.file_edit_transaction import (
    FileEditTransactionCoordinator,
)


class _FakeEventStream:
    def __init__(self) -> None:
        self.events: list[tuple[object, EventSource]] = []

    def add_event(self, event: object, source: EventSource) -> None:
        self.events.append((event, source))


def _metadata(tool_call_id: str, *, response_id: str = 'resp_1') -> ToolCallMetadata:
    return ToolCallMetadata(
        function_name='replace_string',
        tool_call_id=tool_call_id,
        model_response={'id': response_id},
        total_calls_in_response=3,
    )


def _replace_action(tool_call_id: str, path: str = 'doc.txt') -> FileEditAction:
    action = FileEditAction(
        path=path,
        command='replace_string',
        old_string='old',
        new_str='new',
    )
    action.response_id = 'resp_1'
    action.tool_call_metadata = _metadata(tool_call_id)
    return action


def _controller(tmp_path, pending) -> SimpleNamespace:
    return SimpleNamespace(
        runtime=SimpleNamespace(workspace_root=tmp_path),
        agent=SimpleNamespace(pending_actions=pending),
        event_stream=_FakeEventStream(),
    )


def test_same_response_edit_failure_rolls_back_prior_edit_and_skips_remaining(
    tmp_path,
):
    target = tmp_path / 'doc.txt'
    target.write_text('one\ntwo\n', encoding='utf-8')

    first = _replace_action('call_1')
    second = _replace_action('call_2')
    third = _replace_action('call_3')
    pending = deque([second, third])
    controller = _controller(tmp_path, pending)
    coordinator = FileEditTransactionCoordinator(controller)

    coordinator.before_action(first)
    target.write_text('ONE\ntwo\n', encoding='utf-8')
    success = FileEditObservation(content='edited', path='doc.txt')
    success.tool_result = {'ok': True}
    coordinator.after_observation(first, success)

    assert pending.popleft() is second
    coordinator.before_action(second)
    failure = ErrorObservation('replace_string old_string was not found')
    failure.tool_result = {'ok': False}

    coordinator.after_observation(second, failure)

    assert target.read_text(encoding='utf-8') == 'one\ntwo\n'
    assert list(pending) == []
    assert 'FILE_EDIT_TRANSACTION_ROLLBACK' in failure.content
    assert failure.tool_result is not None
    assert failure.tool_result['error_code'] == 'FILE_EDIT_TRANSACTION_ROLLED_BACK'
    assert failure.tool_result['restored_files'] == ['doc.txt']
    assert failure.tool_result['skipped_tool_call_ids'] == ['call_3']

    emitted = controller.event_stream.events
    assert len(emitted) == 1
    skipped_obs, source = emitted[0]
    assert source == EventSource.ENVIRONMENT
    assert isinstance(skipped_obs, ErrorObservation)
    assert skipped_obs.tool_call_metadata is not None
    assert skipped_obs.tool_call_metadata.tool_call_id == 'call_3'
    assert skipped_obs.tool_result is not None
    assert skipped_obs.tool_result['error_code'] == 'FILE_EDIT_TRANSACTION_ABORTED'


def test_single_edit_failure_does_not_roll_back_without_same_response_batch(tmp_path):
    target = tmp_path / 'doc.txt'
    target.write_text('one\n', encoding='utf-8')

    action = _replace_action('call_1')
    coordinator = FileEditTransactionCoordinator(_controller(tmp_path, deque()))

    coordinator.before_action(action)
    target.write_text('ONE\n', encoding='utf-8')
    failure = ErrorObservation('replace_string old_string was not found')
    failure.tool_result = {'ok': False}
    coordinator.after_observation(action, failure)

    assert target.read_text(encoding='utf-8') == 'ONE\n'
    assert 'FILE_EDIT_TRANSACTION_ROLLBACK' not in failure.content
