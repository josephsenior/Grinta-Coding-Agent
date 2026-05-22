from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.engine.file_edit_protocol import get_transaction_store
from backend.engine.orchestrator import Orchestrator
from backend.ledger.action import AgentThinkAction, FileEditAction


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.config = SimpleNamespace(model='fake-model')

    def completion(self, **params):
        self.calls.append(params)
        content = self.responses.pop(0)
        return SimpleNamespace(
            id=f'editor_resp_{len(self.calls)}',
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content, tool_calls=[])
                )
            ],
        )


class EmptyMemory:
    def condense_history(self, _state):
        return SimpleNamespace(events=[], pending_action=None)

    def get_initial_user_message(self, _history):
        return None

    def build_messages(self, **_kwargs):
        return []


class FakeState:
    session_id = 'editor_session'
    history: list = []

    def to_llm_metadata(self, **kwargs):
        return kwargs


def _agent(tmp_path, responses: list[str]) -> Orchestrator:
    agent = object.__new__(Orchestrator)
    agent.llm = FakeLLM(responses)
    agent.executor = SimpleNamespace(_llm=agent.llm)
    agent.memory_manager = EmptyMemory()
    agent.config = SimpleNamespace(
        project_root=str(tmp_path),
        workspace_mount_path_in_runtime=None,
        sid='editor_session',
    )
    agent.event_stream = SimpleNamespace(sid='editor_session')
    return agent


def _response(txn, content: str) -> str:
    return (
        '<file_edit>\n'
        f'{content}'
        f'{txn.delimiter}\n'
        '</file_edit>\n'
    )


def _fenced_response(txn, content: str) -> str:
    return '```xml\n' + _response(txn, content) + '```\n'


@pytest.mark.asyncio
async def test_active_transaction_calls_model_with_tools_disabled(tmp_path):
    store = get_transaction_store()
    session_id = 'editor_session'
    txn = store.create_transaction(
        session_id,
        'app.py',
        'create',
        {'security_risk': 'LOW'},
    )
    agent = _agent(tmp_path, [_response(txn, 'print(1)\n')])

    action = await agent._execute_editor_mode_if_active(FakeState())

    assert isinstance(action, FileEditAction)
    assert agent.llm.calls[0]['tools'] == []
    assert store.get_active_transaction(session_id) is None


@pytest.mark.asyncio
async def test_editor_mode_uses_minimal_prompt_messages(tmp_path):
    store = get_transaction_store()
    txn = store.create_transaction(
        'editor_session',
        'app.py',
        'create',
        {'security_risk': 'LOW'},
    )
    agent = _agent(tmp_path, [_response(txn, 'print(1)\n')])

    await agent._execute_editor_mode_if_active(FakeState())

    messages = agent.llm.calls[0]['messages']
    assert [message['role'] for message in messages] == ['system', 'user']
    assert all('tool_calls' not in message for message in messages)


@pytest.mark.asyncio
async def test_fenced_editor_response_is_unwrapped_and_applied(tmp_path):
    store = get_transaction_store()
    txn = store.create_transaction(
        'editor_session',
        'app.py',
        'create',
        {'security_risk': 'LOW'},
    )
    agent = _agent(tmp_path, [_fenced_response(txn, 'print(1)\n')])

    action = await agent._execute_editor_mode_if_active(FakeState())

    assert isinstance(action, FileEditAction)
    assert action.file_text == 'print(1)\n'
    assert len(agent.llm.calls) == 1


@pytest.mark.asyncio
async def test_valid_editor_response_gets_parsed_and_applied(tmp_path):
    store = get_transaction_store()
    txn = store.create_transaction(
        'editor_session',
        'app.py',
        'replace_range',
        {'start_line': 2, 'end_line': 3, 'security_risk': 'LOW'},
    )
    agent = _agent(tmp_path, [_response(txn, '    return 42\n')])

    action = await agent._execute_editor_mode_if_active(FakeState())

    assert isinstance(action, FileEditAction)
    assert action.command == 'edit'
    assert action.edit_mode == 'range'
    assert action.new_str == '    return 42\n'


@pytest.mark.asyncio
async def test_parse_failure_retries_editor_mode(tmp_path):
    store = get_transaction_store()
    txn = store.create_transaction(
        'editor_session',
        'app.py',
        'create',
        {'security_risk': 'LOW'},
    )
    agent = _agent(tmp_path, ['bad response', _response(txn, 'print(2)\n')])

    action = await agent._execute_editor_mode_if_active(FakeState())

    assert isinstance(action, FileEditAction)
    assert len(agent.llm.calls) == 2
    assert txn.retry_count == 1


@pytest.mark.asyncio
async def test_max_parse_retries_clears_transaction(tmp_path):
    store = get_transaction_store()
    txn = store.create_transaction(
        'editor_session',
        'app.py',
        'create',
        {'security_risk': 'LOW'},
    )
    txn.max_retries = 1
    store.update_transaction('editor_session', txn)
    agent = _agent(tmp_path, ['bad one', 'bad two'])

    action = await agent._execute_editor_mode_if_active(FakeState())

    assert isinstance(action, AgentThinkAction)
    assert 'EDITOR_PARSE_FAILED' in action.thought
    assert store.get_active_transaction('editor_session') is None
    assert len(agent.llm.calls) == 2


@pytest.mark.asyncio
async def test_successful_apply_action_clears_transaction(tmp_path):
    store = get_transaction_store()
    txn = store.create_transaction(
        'editor_session',
        'app.py',
        'create',
        {'security_risk': 'LOW'},
    )
    agent = _agent(tmp_path, [_response(txn, 'print(3)\n')])

    await agent._execute_editor_mode_if_active(FakeState())

    assert store.get_active_transaction('editor_session') is None


@pytest.mark.asyncio
async def test_huge_malformed_response_is_not_returned_wholesale(tmp_path):
    store = get_transaction_store()
    txn = store.create_transaction(
        'editor_session',
        'app.py',
        'create',
        {'security_risk': 'LOW'},
    )
    txn.max_retries = 0
    store.update_transaction('editor_session', txn)
    huge = _response(txn, 'x' * 120000 + '\n')
    agent = _agent(tmp_path, [huge])

    action = await agent._execute_editor_mode_if_active(FakeState())

    assert isinstance(action, AgentThinkAction)
    assert len(action.thought) < 1000
    assert 'x' * 1000 not in action.thought
