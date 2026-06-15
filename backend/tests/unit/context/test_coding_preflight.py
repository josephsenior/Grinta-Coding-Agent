"""Unit tests for coding preflight heuristics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.context import coding_preflight as cp


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('', True),
        ('What does this function do?', True),
        ('Please review the architecture', True),
        ('Fix the login bug in backend/auth.py', False),
        ('Implement a new API endpoint for users', False),
    ],
)
def test_looks_read_only(text: str, expected: bool) -> None:
    assert cp._looks_read_only(text) is expected


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('hi', False),
        ('Explain the repo layout', False),
        ('Refactor backend/cli module for clarity', True),
        ('Update tests in test_auth.py', True),
    ],
)
def test_looks_like_coding_task(text: str, expected: bool) -> None:
    assert cp._looks_like_coding_task(text) is expected


def test_message_text_handles_string_and_blocks() -> None:
    assert cp._message_text('plain') == 'plain'
    assert cp._message_text([{'text': 'one'}, {'text': 'two'}]) == 'one\ntwo'
    assert cp._message_text(42) == ''


def test_last_user_text_reads_latest_user_message() -> None:
    messages = [
        {'role': 'assistant', 'content': 'ignored'},
        {'role': 'user', 'content': 'first'},
        {'role': 'user', 'content': 'latest'},
    ]
    assert cp._last_user_text(messages) == 'latest'


def test_already_started_current_turn_detects_follow_up_events() -> None:
    class MessageAction:
        def __init__(self) -> None:
            self.source = SimpleNamespace(name='USER')

    class CmdRunAction:
        pass

    state = SimpleNamespace(history=[MessageAction(), CmdRunAction()])
    assert cp._already_started_current_turn(state) is True


def test_format_list_and_candidates() -> None:
    assert cp._format_list('Dirty files', []) == '- Dirty files: none detected'
    assert cp._format_list('Dirty files', ['a.py']) == '- Dirty files: a.py'
    lines = cp._format_candidate_lines(
        [SimpleNamespace(path='a.py', score=3, reasons=['mentioned'], symbols=['Foo'])]
    )
    assert any('a.py' in line for line in lines)


def test_build_coding_preflight_block_skips_chat_and_started_turns(tmp_path) -> None:
    state = SimpleNamespace(history=[])
    config = SimpleNamespace()
    messages = [{'role': 'user', 'content': 'Refactor backend/auth.py token refresh'}]
    with patch.object(cp, 'resolve_cli_workspace_directory', return_value=tmp_path):
        block = cp.build_coding_preflight_block(messages, state, config, mode='default')
    assert '<CODING_PREFLIGHT>' in block
    assert cp.build_coding_preflight_block(messages, state, config, mode='chat') == ''


def test_build_coding_preflight_block_without_workspace() -> None:
    state = SimpleNamespace(history=[])
    config = SimpleNamespace()
    messages = [{'role': 'user', 'content': 'Fix backend/api.py endpoint bug'}]
    with patch.object(cp, 'resolve_cli_workspace_directory', return_value=None):
        block = cp.build_coding_preflight_block(messages, state, config, mode='default')
    assert 'Workspace: unavailable' in block


def test_already_started_skips_preflight(tmp_path) -> None:
    class MessageAction:
        def __init__(self) -> None:
            self.source = SimpleNamespace(name='USER')

    class CmdRunAction:
        pass

    state = SimpleNamespace(history=[MessageAction(), CmdRunAction()])
    config = SimpleNamespace()
    messages = [{'role': 'user', 'content': 'Refactor backend/auth.py token refresh'}]
    with patch.object(cp, 'resolve_cli_workspace_directory', return_value=tmp_path):
        assert cp.build_coding_preflight_block(messages, state, config, mode='default') == ''


def test_source_name_handles_enum_like_values() -> None:
    assert cp._source_name(SimpleNamespace(name='USER')) == 'USER'
    assert cp._source_name(SimpleNamespace(value='assistant')) == 'assistant'
    assert cp._source_name(None) == ''


def test_tokens_and_empty_candidate_lines() -> None:
    assert 'fix' in cp._tokens('Fix backend auth bug')
    assert cp._format_candidate_lines([])[0].startswith('- Ranked candidates: none')
