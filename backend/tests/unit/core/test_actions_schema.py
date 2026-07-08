from typing import Any, cast

import pytest
from pydantic import ValidationError

from backend.core.schemas.actions import (
    AgentThinkActionSchema,
    BrowseInteractiveActionSchema,
    CondensationActionSchema,
    CondensationRequestActionSchema,
    DelegateTaskActionSchema,
    MCPActionSchema,
    RecallActionSchema,
    StreamingChunkActionSchema,
    TaskTrackingActionSchema,
)


def test_condensation_action_schema():
    data = {
        'action_type': 'condensation',
        'pruned_event_ids': [1, 2, 3],
        'summary': 'Forgot 1, 2, 3',
    }
    action = CondensationActionSchema(**data)
    assert action.action_type == 'condensation'
    assert action.pruned_event_ids == [1, 2, 3]
    assert action.summary == 'Forgot 1, 2, 3'


def test_condensation_request_action_schema():
    data = {'action_type': 'condensation_request'}
    action = CondensationRequestActionSchema(**data)
    assert action.action_type == 'condensation_request'


def test_agent_think_action_schema():
    data = {'action_type': 'think', 'thought': 'Thinking about the next step'}
    action = AgentThinkActionSchema(**data)
    assert action.action_type == 'think'
    assert action.runnable is False
    assert action.thought == 'Thinking about the next step'


def test_mcp_action_schema():
    data = {
        'action_type': 'call_tool_mcp',
        'name': 'weather_tool',
        'arguments': {'city': 'London'},
    }
    action = MCPActionSchema(**data)
    assert action.action_type == 'call_tool_mcp'
    assert action.runnable is True
    assert action.name == 'weather_tool'
    assert action.arguments['city'] == 'London'


def test_recall_action_schema():
    data = {
        'action_type': 'recall',
        'query': 'something from past',
        'recall_type': 'user_preference',
    }
    action = RecallActionSchema(**data)
    assert action.action_type == 'recall'
    assert action.query == 'something from past'
    assert action.recall_type == 'user_preference'


def test_streaming_chunk_action_schema():
    data = {
        'action_type': 'streaming_chunk',
        'chunk': 'Hello',
        'accumulated': 'Hello',
        'is_final': False,
    }
    action = StreamingChunkActionSchema(**data)
    assert action.action_type == 'streaming_chunk'
    assert action.chunk == 'Hello'
    assert action.accumulated == 'Hello'
    assert action.suppress_live_response is False

    suppressing = StreamingChunkActionSchema(
        action_type='streaming_chunk',
        chunk='',
        accumulated='',
        is_final=True,
        suppress_live_response=True,
    )
    assert suppressing.suppress_live_response is True


def test_task_tracking_action_schema():
    data = {
        'action_type': 'task_tracking',
        'command': 'update',
        'task_list': [{'id': '1', 'status': 'todo'}],
    }
    action = TaskTrackingActionSchema(**data)
    assert action.action_type == 'task_tracking'
    assert action.command == 'update'
    assert len(action.task_list) == 1


def test_delegate_task_action_schema():
    data = {
        'action_type': 'delegate_task',
        'task_description': 'Do this',
        'files': ['file1.py'],
        'parallel_tasks': [],
    }
    action = DelegateTaskActionSchema(**data)
    assert action.action_type == 'delegate_task'
    assert action.runnable is True
    assert action.task_description == 'Do this'
    assert 'file1.py' in action.files


def test_browse_interactive_action_schema():
    data = {'action_type': 'browse_interactive', 'browser_actions': 'click(10, 20)'}
    action = BrowseInteractiveActionSchema(**data)
    assert action.action_type == 'browse_interactive'
    assert action.runnable is True
    assert action.browser_actions == 'click(10, 20)'


def test_validation_error():
    with pytest.raises(ValidationError):
        cast(Any, MCPActionSchema)(action_type='mcp')  # Missing name
