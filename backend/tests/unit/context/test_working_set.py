"""Tests for durable working-set context."""

from __future__ import annotations

from unittest.mock import patch

from backend.context.working_set import (
    get_durable_context_block,
    sync_snapshot_to_working_memory,
)
from backend.ledger.action import MessageAction
from backend.ledger.event import EventSource
from backend.ledger.observation.commands import CmdOutputObservation


def test_sync_snapshot_to_working_memory_updates_sections(tmp_path) -> None:
    snapshot = {
        'test_results': [
            {
                'command': 'pytest -q',
                'status': 'failed',
                'exit_code': 1,
                'output': '18 failed, 9 passed',
            }
        ],
        'decisions': ['Fix message routing in client_set'],
        'attempted_approaches': [
            {'type': 'cmd', 'detail': 'rewrite network.py', 'outcome': 'FAILED: timeout'}
        ],
    }
    from backend.engine.tools.working_memory import set_current_session_id

    set_current_session_id('ws-test')
    memory_file = tmp_path / 'working_memory_ws-test.json'

    with (
        patch('backend.engine.tools.working_memory._memory_path', return_value=memory_file),
        patch(
            'backend.context.pre_condensation_snapshot.format_snapshot_for_injection',
            return_value='<RESTORED_CONTEXT>summary</RESTORED_CONTEXT>',
        ),
    ):
        updated = sync_snapshot_to_working_memory(snapshot)

    assert 'findings' in updated
    assert 'blockers' in updated
    assert memory_file.exists()


def test_get_durable_context_block_includes_task_and_pytest() -> None:
    user = MessageAction(content='Fix the raftkv tests')
    user.source = EventSource.USER
    user.id = 1
    obs = CmdOutputObservation(
        content='======================== 1 failed, 2 passed in 3.0s ========================',
        command='pytest',
        exit_code=1,
    )
    obs.id = 2

    block = get_durable_context_block(
        [user, obs],
        char_budget=2000,
        include_task_from_history=True,
    )

    assert 'Fix the raftkv tests' in block
    assert '1 failed, 2 passed in 3.0s' in block


def test_build_working_set_skips_fresh_session_without_artifacts() -> None:
    from backend.context.working_set import build_working_set_observation
    from backend.ledger.action import MessageAction
    from backend.ledger.event import EventSource

    user = MessageAction(content='Build a raft kv store')
    user.source = EventSource.USER
    user.id = 1

    assert build_working_set_observation([user]) is None


def test_working_set_observation_skips_condensation_boilerplate() -> None:
    from backend.context.observation_processors import convert_observation_to_message
    from backend.ledger.observation.agent import AgentCondensationObservation

    obs = AgentCondensationObservation(
        content='<DURABLE_WORKING_SET>\nTask: Build raft\n<DURABLE_WORKING_SET>',
        is_working_set=True,
    )
    msg = convert_observation_to_message(obs, max_message_chars=None)
    text = msg.content[0].text
    assert 'CONTEXT CONDENSED' not in text
    assert 'Context was condensed' not in text
    assert 'Build raft' in text
