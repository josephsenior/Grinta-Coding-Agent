"""Tests for compact multi_edit and read(symbols) error formatting."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.core.errors import FunctionCallValidationError, ToolExecutionError
from backend.core.errors.structured_edit_errors import (
    compact_symbol_candidates,
    compact_syntax_detail,
    format_agent_edit_error_message,
    multi_edit_raise,
    normalize_edit_exception,
    normalize_editor_error_response,
    summarize_editor_error,
    symbol_ambiguity_summary,
)
from backend.execution.aes import helpers as h
from backend.ledger.observation import ErrorObservation


def test_compact_symbol_candidates_trims_fields() -> None:
    candidates = [
        {
            'symbol_id': 'src/a.py:10-15:login',
            'qualified_name': 'login',
            'path': 'src/a.py',
            'start_line': 10,
            'end_line': 15,
            'signature': 'def login():',
            'preview': 'def login():',
        }
    ]
    compact = compact_symbol_candidates(candidates)
    assert compact == [
        {
            'symbol_id': 'src/a.py:10-15:login',
            'qualified_name': 'login',
            'path': 'src/a.py',
            'start_line': 10,
        }
    ]


def test_summarize_editor_error_maps_old_string_not_found() -> None:
    result = SimpleNamespace(
        error='replace_string old_string was not found exactly.',
        error_code='OLD_STRING_NOT_FOUND',
        retryable=True,
        operation='replace_string',
        metadata={'match_count': 0},
    )
    code, summary, retryable, extra = summarize_editor_error(result)
    assert code == 'OLD_STRING_NOT_FOUND'
    assert summary == 'replace_string failed: old_string not found exactly.'
    assert retryable is True
    assert extra['match_count'] == 0


def test_compact_syntax_detail_strips_content_context() -> None:
    raw = (
        'INTRODUCED_SYNTAX_ERROR: edit introduced syntax errors.\n'
        'SyntaxError: invalid syntax at line 42\n\n'
        'Content context:\n  [line 42 — excerpt]'
    )
    assert compact_syntax_detail(raw) == 'SyntaxError: invalid syntax at line 42'


def test_multi_edit_raise_builds_structured_tool_execution_error() -> None:
    with pytest.raises(ToolExecutionError) as exc_info:
        multi_edit_raise(
            'replace_string failed: old_string not found exactly.',
            error_code='OLD_STRING_NOT_FOUND',
            path='src/config.py',
            operation='replace_string',
            failed_op_index=1,
            total_ops=3,
            retryable=True,
            match_count=0,
        )
    exc = exc_info.value
    assert 'replace_string failed: old_string not found exactly.' in str(exc)
    assert 'File: src/config.py' in str(exc)
    assert 'Op index: 1 (2/3)' in str(exc)
    assert exc.context['error_code'] == 'OLD_STRING_NOT_FOUND'
    assert exc.context['failed_path'] == 'src/config.py'
    assert 'payload' not in exc.context


def test_normalize_edit_exception_from_tool_execution_error() -> None:
    exc = ToolExecutionError(
        'replace_string failed: old_string not found exactly.\n'
        'File: src/b.py\n'
        'Op index: 1 (2/5)\n'
        'No files were modified.',
        context={
            'error_code': 'OLD_STRING_NOT_FOUND',
            'retryable': True,
            'files_modified': 0,
            'failed_path': 'src/b.py',
            'failed_op_index': 1,
            'total_ops': 5,
            'failed_operation': 'replace_string',
            'operation': 'replace_string',
        },
    )
    payload = {
        'file_edits': [
            {
                'path': 'src/a.py',
                'operation': 'replace_string',
                'old_string': 'x',
                'new_string': 'y',
            },
            {
                'path': 'src/b.py',
                'operation': 'replace_string',
                'old_string': 'missing',
                'new_string': 'z',
            },
        ]
    }
    message, tool_result = normalize_edit_exception(exc, payload, command='multi_edit')
    assert 'old_string not found' in message
    assert tool_result['error_code'] == 'OLD_STRING_NOT_FOUND'
    assert tool_result['failed_op_index'] == 1
    assert tool_result['total_ops'] == 5
    assert 'payload' not in tool_result


def test_normalize_edit_exception_from_validation_error() -> None:
    exc = FunctionCallValidationError(
        "multiedit validation failed: item 2 missing required field 'path'."
    )
    payload = {
        'file_edits': [
            {
                'path': 'a.py',
                'operation': 'replace_string',
                'old_string': 'a',
                'new_string': 'b',
            },
            {
                'path': 'b.py',
                'operation': 'replace_string',
                'old_string': 'a',
                'new_string': 'b',
            },
            {'operation': 'replace_string', 'old_string': 'a', 'new_string': 'b'},
        ]
    }
    message, tool_result = normalize_edit_exception(exc, payload, command='multi_edit')
    assert 'item 2' in message
    assert tool_result['error_code'] == 'VALIDATION_ERROR'
    assert tool_result['failed_op_index'] == 2
    assert 'payload' not in tool_result


def test_make_edit_error_obs_omits_payload() -> None:
    exc = ToolExecutionError(
        'replace_string failed: old_string not found exactly.\n'
        'File: b.py\n'
        'No files were modified.',
        context={
            'error_code': 'OLD_STRING_NOT_FOUND',
            'retryable': True,
            'files_modified': 0,
            'failed_path': 'b.py',
            'failed_operation': 'replace_string',
            'operation': 'replace_string',
        },
    )
    payload = {
        'file_edits': [
            {
                'path': 'b.py',
                'operation': 'replace_string',
                'old_string': 'HUGE',
                'new_string': 'CONTENT',
            }
        ]
    }
    obs = h._make_edit_error_obs(exc, payload, command='multi_edit')
    assert isinstance(obs, ErrorObservation)
    assert 'HUGE' not in obs.content
    assert obs.tool_result is not None
    assert 'payload' not in obs.tool_result
    assert obs.tool_result['error_code'] == 'OLD_STRING_NOT_FOUND'


def test_symbol_ambiguity_summary_is_compact() -> None:
    summary = symbol_ambiguity_summary('login', [{}, {}])
    assert 'ambiguous (2 matches)' in summary
    assert 'find_symbols' not in summary


def test_format_verification_failure_message() -> None:
    from backend.core.errors.structured_edit_errors import (
        build_verification_failure_tool_result,
        format_verification_failure_message,
    )

    message = format_verification_failure_message('src/missing.py')
    assert 'verification failed' in message
    assert 'src/missing.py' in message
    assert 'Original observation' not in message
    tool_result = build_verification_failure_tool_result('src/missing.py')
    assert tool_result['error_code'] == 'VERIFICATION_FILE_MISSING'
    assert tool_result['path'] == 'src/missing.py'


def test_create_file_schema_exposes_overwrite_param() -> None:
    from backend.engine.tools.native_file_tools import create_create_file_tool

    params = create_create_file_tool()['function']['parameters']
    assert 'overwrite' in params['properties']
    assert 'overwrite' not in params['required']


def test_normalize_editor_error_response_create_file_exists() -> None:
    result = SimpleNamespace(
        error=(
            'File exists. To modify it, use replace_string (preferred). '
            'If you intend to replace the entire contents, retry with overwrite=true.'
        ),
        error_code='CREATE_FILE_ALREADY_EXISTS',
        retryable=True,
        operation='create_file',
        old_content='print("old")\n',
    )
    message, tool_result = normalize_editor_error_response(
        result,
        path='existing.py',
        command='create_file',
    )
    assert 'File exists' in message
    assert 'replace_string' in message
    assert 'overwrite=true' in message
    assert tool_result['error_code'] == 'CREATE_FILE_ALREADY_EXISTS'
    assert tool_result['path'] == 'existing.py'


def test_normalize_editor_error_response_compact() -> None:
    result = SimpleNamespace(
        error='replace_string old_string was not found exactly.',
        error_code='OLD_STRING_NOT_FOUND',
        retryable=True,
        operation='replace_string',
        metadata={'match_count': 0},
    )
    message, tool_result = normalize_editor_error_response(
        result,
        path='src/config.py',
        command='replace_string',
    )
    assert 'old_string not found' in message
    assert 'File: src/config.py' in message
    assert tool_result['error_code'] == 'OLD_STRING_NOT_FOUND'
    assert tool_result['path'] == 'src/config.py'
    assert 'payload' not in tool_result


def test_build_search_error_tool_result() -> None:
    from backend.core.errors.structured_edit_errors import (
        build_search_error_tool_result,
    )

    tool_result = build_search_error_tool_result(
        tool='grep',
        message='Path does not exist: missing/',
        pattern='foo',
        path='missing/',
        output_mode='content',
    )
    assert tool_result['error_code'] == 'PATH_NOT_FOUND'
    assert tool_result['pattern'] == 'foo'
    assert tool_result['ok'] is False


def test_build_search_error_observation() -> None:
    from backend.core.errors.structured_edit_errors import (
        build_search_error_observation,
    )
    from backend.ledger.observation import ErrorObservation

    obs = build_search_error_observation(
        tool='grep',
        message='Path does not exist: missing/',
        pattern='foo',
        path='missing/',
        output_mode='content',
    )
    assert isinstance(obs, ErrorObservation)
    assert 'Path does not exist' in obs.content
    assert obs.tool_result['error_code'] == 'PATH_NOT_FOUND'


def test_format_agent_edit_error_message_includes_rollback() -> None:
    message = format_agent_edit_error_message(
        {
            'failed_path': 'src/a.py',
            'transaction_rolled_back': True,
            'files_modified': 0,
        },
        fallback='multi_edit transaction rolled back.',
    )
    assert 'Transaction rolled back' in message
    assert 'No files were modified' in message
