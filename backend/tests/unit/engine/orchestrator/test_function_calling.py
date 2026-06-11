"""Tests for backend.engine.function_calling."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from backend.core.errors import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
)
from backend.engine.function_calling import (
    _handle_cmd_run_tool,
    _handle_mcp_tool,
    _handle_summarize_context_tool,
    _handle_task_tracker_tool,
    _process_single_tool_call,
    combine_thought,
    response_to_actions,
    set_security_risk,
)
from backend.engine.tools import create_cmd_run_tool
from backend.engine.tools.task_tracker import (
    create_task_tracker_tool,
)
from backend.ledger.action import (
    CmdRunAction,
    MessageAction,
    TaskTrackingAction,
)
from backend.ledger.action.agent import CondensationRequestAction
from backend.ledger.action.mcp import MCPAction


@pytest.fixture(autouse=True)
def _workspace_dir_for_task_tracker(tmp_path, monkeypatch):
    """Task tracker persistence now requires an explicit workspace root."""
    monkeypatch.setattr(
        'backend.core.workspace_resolution.require_effective_workspace_root',
        lambda: tmp_path,
    )
    return tmp_path


def _model_response(*, content: str = '', tool_calls: list[Any] | None = None) -> Any:
    return SimpleNamespace(
        id='resp_1',
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    tool_calls=tool_calls or [],
                )
            )
        ],
    )


def _native_tool_call(name: str, arguments: dict[str, Any]) -> Any:
    return SimpleNamespace(
        id='call_1',
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments),
        ),
    )


# ---------------------------------------------------------------------------
# combine_thought
# ---------------------------------------------------------------------------


class TestCombineThought:
    def test_sets_thought_when_empty(self):
        action = CmdRunAction(command='ls')
        cast(Any, action).thought = ''
        result = combine_thought(action, 'new thought')
        assert cast(Any, result).thought == 'new thought'

    def test_prepends_when_already_has_thought(self):
        action = CmdRunAction(command='ls')
        cast(Any, action).thought = 'existing thought'
        result = combine_thought(action, 'prefix')
        assert cast(Any, result).thought == 'prefix\nexisting thought'

    def test_grep_action_not_polluted_with_assistant_prose(self):
        from backend.engine.common import process_tool_calls
        from backend.engine.tools._tool_handlers import _handle_grep_tool
        from backend.ledger.action.search import GrepAction

        assistant_msg = SimpleNamespace(
            tool_calls=[
                SimpleNamespace(
                    id='call_1',
                    function=SimpleNamespace(
                        name='grep',
                        arguments=json.dumps(
                            {
                                'pattern': '_start_election',
                                'path': 'raftkv/node.py',
                            }
                        ),
                    ),
                )
            ]
        )
        response = SimpleNamespace(id='resp_1')

        actions = process_tool_calls(
            assistant_msg,
            response,
            lambda _tc, args: _handle_grep_tool(args),
            lambda _msg: "I can't read that file. Let me use grep.",
            combine_thought,
        )

        assert len(actions) == 1
        assert isinstance(actions[0], GrepAction)
        assert actions[0].pattern == '_start_election'
        assert actions[0].path == 'raftkv/node.py'
        assert actions[0].thought == ''

    def test_empty_thought_no_change(self):
        action = CmdRunAction(command='ls')
        cast(Any, action).thought = 'existing'
        result = combine_thought(action, '')
        assert cast(Any, result).thought == 'existing'

    def test_returns_action_unchanged_when_no_thought_attr(self):
        action = MagicMock(spec=[])  # no 'thought' attribute
        result = combine_thought(action, 'some thought')
        assert result is action


class TestResponseToActions:
    def test_plain_text_without_tool_calls_persists_message(self):
        response = _model_response(content='Here is the status update.')

        actions = response_to_actions(response)

        assert len(actions) == 1
        assert isinstance(actions[0], MessageAction)
        assert actions[0].content == 'Here is the status update.'
        assert actions[0].wait_for_response is False
        assert actions[0].final_response is True
        assert actions[0].suppress_cli is False
        assert actions[0].transcript_only is False

    def test_native_tool_call_with_content_persists_transcript_message(self):
        tool_name = create_cmd_run_tool()['function']['name']
        response = _model_response(
            content='I will run the check.\n[END_TOOL_CALL]',
            tool_calls=[
                _native_tool_call(
                    tool_name,
                    {'command': 'echo ok', 'security_risk': 'LOW'},
                )
            ],
        )

        actions = response_to_actions(response)

        assert len(actions) == 2
        assert isinstance(actions[0], MessageAction)
        assert actions[0].content == 'I will run the check.'
        assert actions[0].wait_for_response is False
        assert actions[0].transcript_only is True
        assert isinstance(actions[1], CmdRunAction)


# ---------------------------------------------------------------------------
# set_security_risk
# ---------------------------------------------------------------------------


class TestSetSecurityRisk:
    def test_sets_valid_risk_level(self):
        action = CmdRunAction(command='ls')
        set_security_risk(action, {'security_risk': 'SAFE'})
        # Should not raise; SAFE may or may not be in RISK_LEVELS, no error

    def test_invalid_risk_level_logs_warning(self):
        action = CmdRunAction(command='ls')
        # Should not raise even with an invalid level
        with patch('backend.engine.function_calling_helpers.logger') as mock_log:
            set_security_risk(action, {'security_risk': 'NUCLEAR'})
        mock_log.warning.assert_called_once()

    def test_no_security_risk_key_does_nothing(self):
        action = CmdRunAction(command='ls')
        original_risk = getattr(action, 'security_risk', None)
        set_security_risk(action, {})
        assert getattr(action, 'security_risk', None) == original_risk


# ---------------------------------------------------------------------------
# _handle_cmd_run_tool
# ---------------------------------------------------------------------------


class TestHandleCmdRunTool:
    def test_basic_command(self):
        action = _handle_cmd_run_tool({'command': 'echo hello', 'security_risk': 'LOW'})
        assert isinstance(action, CmdRunAction)
        assert action.command == 'echo hello'

    def test_missing_command_raises(self):
        with pytest.raises(FunctionCallValidationError, match='command'):
            _handle_cmd_run_tool({})

    def test_timeout_set(self):
        action = _handle_cmd_run_tool(
            {'command': 'sleep 2', 'timeout': '5.5', 'security_risk': 'LOW'}
        )
        assert isinstance(action, CmdRunAction)

    def test_invalid_timeout_raises(self):
        with pytest.raises(FunctionCallValidationError, match='timeout'):
            _handle_cmd_run_tool(
                {'command': 'echo', 'timeout': 'not-a-number', 'security_risk': 'LOW'}
            )

    def test_is_input_flag(self):
        action = _handle_cmd_run_tool(
            {'command': 'y', 'is_input': 'true', 'security_risk': 'LOW'}
        )
        assert action.is_input is True

    def test_is_input_false_default(self):
        action = _handle_cmd_run_tool({'command': 'ls', 'security_risk': 'LOW'})
        assert action.is_input is False

    def test_missing_security_risk_raises(self):
        with pytest.raises(FunctionCallValidationError, match='security_risk'):
            _handle_cmd_run_tool({'command': 'ls'})


# ---------------------------------------------------------------------------
# _handle_summarize_context_tool
# ---------------------------------------------------------------------------


class TestHandleCondensationRequestTool:
    def test_creates_condensation_request_action(self):
        action = _handle_summarize_context_tool({})
        assert isinstance(action, CondensationRequestAction)


# ---------------------------------------------------------------------------
# _handle_mcp_tool
# ---------------------------------------------------------------------------


class TestHandleMcpTool:
    def test_creates_mcp_action_with_dict_args(self):
        action = _handle_mcp_tool('my_mcp_tool', {'key': 'value'})
        assert isinstance(action, MCPAction)
        assert action.name == 'my_mcp_tool'
        assert action.arguments == {'key': 'value'}

    def test_non_mapping_args_defaults_to_empty(self):
        action = _handle_mcp_tool('tool_x', None)
        assert isinstance(action, MCPAction)
        assert action.arguments == {}

    def test_mcp_action_with_empty_args(self):
        action = _handle_mcp_tool('my_tool', {})
        assert isinstance(action, MCPAction)
        assert action.arguments == {}


# ---------------------------------------------------------------------------
# _handle_task_tracker_tool
# ---------------------------------------------------------------------------


class TestHandleTaskTrackerTool:
    def test_update_command_with_task_list(self):
        args = {
            'command': 'update',
            'task_list': [
                {'id': 'task-1', 'description': 'Do X', 'status': 'todo'},
            ],
        }
        action = _handle_task_tracker_tool(args)
        assert isinstance(action, TaskTrackingAction)
        assert action.command == 'update'
        assert len(action.task_list) == 1

    def test_missing_command_raises(self):
        with pytest.raises(FunctionCallValidationError, match='command'):
            _handle_task_tracker_tool({})

    def test_update_without_task_list_raises(self):
        with pytest.raises(FunctionCallValidationError, match='task_list'):
            _handle_task_tracker_tool({'command': 'update'})

    def test_task_list_not_list_raises(self):
        with pytest.raises(FunctionCallValidationError):
            _handle_task_tracker_tool({'command': 'update', 'task_list': 'not a list'})

    def test_task_item_not_dict_raises(self):
        with pytest.raises(FunctionCallValidationError):
            _handle_task_tracker_tool(
                {'command': 'update', 'task_list': ['not a dict']}
            )

    def test_normalizes_missing_task_fields(self):
        args = {
            'command': 'update',
            'task_list': [{'description': 'My task'}],  # missing id, status
        }
        action = cast(TaskTrackingAction, _handle_task_tracker_tool(args))
        task = action.task_list[0]
        assert task['id'] == 'step-1'
        assert task['status'] == 'todo'

    def test_normalizes_canonical_task_fields(self):
        args = {
            'command': 'update',
            'task_list': [
                {
                    'description': 'Top level',
                    'status': 'todo',
                    'result': 'In progress note',
                    'subtasks': [{'description': 'Child step', 'status': 'done'}],
                }
            ],
        }
        action = cast(TaskTrackingAction, _handle_task_tracker_tool(args))
        task = action.task_list[0]
        assert task['description'] == 'Top level'
        # All subtasks are done → parent is auto-promoted to done
        assert task['status'] == 'done'
        assert task['result'] == 'In progress note'
        assert task['subtasks'][0]['description'] == 'Child step'
        assert task['subtasks'][0]['status'] == 'done'

    def test_normalizes_skipped_and_blocked_statuses(self):
        args = {
            'command': 'update',
            'task_list': [
                {'id': 'a', 'description': 'Skip me', 'status': 'skipped'},
                {'id': 'b', 'description': 'Blocked', 'status': 'blocked'},
            ],
        }
        action = cast(TaskTrackingAction, _handle_task_tracker_tool(args))
        assert action.task_list[0]['status'] == 'skipped'
        assert action.task_list[1]['status'] == 'blocked'

    def test_task_tracker_schema_rejects_status_aliases_in_nested_subtasks(self):
        tool = create_task_tracker_tool()
        parameters = tool['function']['parameters']
        task_item = parameters['properties']['task_list']['items']
        status = task_item['properties']['status']
        nested_status = task_item['properties']['subtasks']['items']['properties'][
            'status'
        ]

        assert status['enum'] == ['todo', 'in_progress', 'done', 'skipped', 'blocked']
        assert nested_status['enum'] == status['enum']
        assert 'in_progress' in status['description']

    @pytest.mark.parametrize('legacy_status', ['pending', 'doing', 'completed'])
    def test_rejects_legacy_task_status_aliases(self, legacy_status: str):
        args = {
            'command': 'update',
            'task_list': [
                {'id': '1', 'description': 'Step 1', 'status': legacy_status},
            ],
        }

        with pytest.raises(FunctionCallValidationError, match='Invalid task status'):
            _handle_task_tracker_tool(args)

    def test_non_plan_command_with_empty_task_list(self):
        args = {'command': 'update', 'task_list': []}
        action = cast(TaskTrackingAction, _handle_task_tracker_tool(args))
        assert action.command == 'update'

    def test_duplicate_update_returns_noop_task_action(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'backend.core.workspace_resolution.workspace_agent_state_dir',
            lambda project_root=None: tmp_path,
        )
        args = {
            'command': 'update',
            'task_list': [{'id': '1', 'description': 'step', 'status': 'in_progress'}],
        }

        first = _handle_task_tracker_tool(args)
        assert isinstance(first, TaskTrackingAction)
        from backend.engine.tools.task_tracker import TaskTracker

        TaskTracker(tmp_path).save_to_file(first.task_list)

        second = _handle_task_tracker_tool(args)
        assert isinstance(second, TaskTrackingAction)
        assert 'unchanged' in second.thought.lower()


# ---------------------------------------------------------------------------
# _process_single_tool_call
# ---------------------------------------------------------------------------


class TestProcessSingleToolCall:
    def _make_tool_call(self, name: str, mcp_names=None):
        tc = MagicMock()
        tc.function.name = name
        tc._mcp_tool_names = mcp_names
        return tc

    def test_dispatches_cmd_run(self):
        from backend.engine.tools.bash import create_cmd_run_tool

        tool_name = create_cmd_run_tool()['function']['name']
        tc = self._make_tool_call(tool_name)
        action = _process_single_tool_call(
            tc, {'command': 'ls', 'security_risk': 'LOW'}
        )
        assert isinstance(action, CmdRunAction)

    def test_finish_is_not_dispatchable(self):
        tc = self._make_tool_call('finish')
        with pytest.raises(FunctionCallNotExistsError):
            _process_single_tool_call(tc, {'summary': 'done'})

    def test_plan_mode_rejects_mutating_file_tool_call(self):
        from backend.engine.tools.native_file_tools import create_create_tool

        tool_name = create_create_tool()['function']['name']
        tc = self._make_tool_call(tool_name)
        with pytest.raises(FunctionCallValidationError, match='Plan Mode'):
            _process_single_tool_call(
                tc,
                {
                    'type': 'file',
                    'path': 'new.py',
                    'content': 'print(1)',
                    'security_risk': 'LOW',
                },
                mode='plan',
            )

    def test_dispatches_mcp_tool(self):
        tc = self._make_tool_call('some_mcp_tool', mcp_names=['some_mcp_tool'])
        action = _process_single_tool_call(tc, {'key': 'val'})
        assert isinstance(action, MCPAction)

    def test_unknown_tool_raises(self):
        tc = self._make_tool_call('definitely_unknown_tool_xyz')
        with pytest.raises(FunctionCallNotExistsError):
            _process_single_tool_call(tc, {})

    def test_unknown_tool_not_in_mcp_list_raises(self):
        tc = self._make_tool_call('other_tool', mcp_names=['some_mcp_tool'])
        with pytest.raises(FunctionCallNotExistsError):
            _process_single_tool_call(tc, {})


class TestMultiEditCommand:
    def test_multi_edit_edits_workspace_scoped_paths(self, tmp_path):
        from backend.engine.function_calling import _handle_multi_edit_command

        (tmp_path / 'src').mkdir()
        (tmp_path / 'src' / 'a.py').write_text('A = 0\n', encoding='utf-8')
        (tmp_path / 'src' / 'b.py').write_text('B = 0\n', encoding='utf-8')

        action = _handle_multi_edit_command(
            '',
            {
                'file_edits': [
                    {
                        'path': 'src/a.py',
                        'operation': 'replace_string',
                        'old_string': 'A = 0\n',
                        'new_string': 'A = 1\n',
                    },
                    {
                        'path': 'src/b.py',
                        'operation': 'replace_string',
                        'old_string': 'B = 0\n',
                        'new_string': 'B = 2\n',
                    },
                ]
            },
        )

        assert isinstance(action, MessageAction)
        assert (tmp_path / 'src' / 'a.py').read_text(encoding='utf-8') == 'A = 1\n'
        assert (tmp_path / 'src' / 'b.py').read_text(encoding='utf-8') == 'B = 2\n'

    def test_multi_edit_rejects_path_traversal(self, tmp_path):
        from backend.engine.function_calling import _handle_multi_edit_command

        with pytest.raises(FunctionCallValidationError, match='invalid path'):
            _handle_multi_edit_command(
                '',
                {
                    'file_edits': [
                        {
                            'path': '../outside.py',
                            'operation': 'replace_string',
                            'old_string': 'old',
                            'new_string': 'new',
                        }
                    ]
                },
            )

        assert not (tmp_path.parent / 'outside.py').exists()

    def test_multi_edit_allows_sequential_duplicate_path_operations(self, tmp_path):
        from backend.engine.function_calling import _handle_multi_edit_command

        py = tmp_path / 'src' / 'a.py'
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text('A = 0\nB = 2\n', encoding='utf-8')

        action = _handle_multi_edit_command(
            '',
            {
                'file_edits': [
                    {
                        'path': 'src/a.py',
                        'operation': 'replace_string',
                        'old_string': 'A = 0\n',
                        'new_string': 'A = 1\n',
                    },
                    {
                        'path': 'src/a.py',
                        'operation': 'symbol_body_replacement',
                        'start_line': 2,
                        'end_line': 2,
                        'content': 'B = 99\n',
                    },
                ]
            },
        )

        assert isinstance(action, MessageAction)
        assert (tmp_path / 'src' / 'a.py').read_text(
            encoding='utf-8'
        ) == 'A = 1\nB = 99\n'

    def test_multi_edit_supports_symbol_body_edit(self, tmp_path):
        from backend.engine.function_calling import _handle_multi_edit_command

        py = tmp_path / 'src' / 'm.py'
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text('def a():\n    return 1\n', encoding='utf-8')

        action = _handle_multi_edit_command(
            '',
            {
                'file_edits': [
                    {
                        'path': 'src/m.py',
                        'operation': 'symbol_body_replacement',
                        'start_line': 1,
                        'end_line': 2,
                        'content': 'def a():\n    return 42\n',
                    }
                ]
            },
        )

        assert isinstance(action, MessageAction)
        assert 'return 42' in py.read_text(encoding='utf-8')


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_run_production_health_check_returns_dict(self):
        from backend.engine.tools.health_check import run_production_health_check

        result = run_production_health_check(raise_on_failure=False)
        assert isinstance(result, dict)
        assert 'overall_status' in result

    def test_ultimate_editor_check_present(self):
        from backend.engine.tools.health_check import run_production_health_check

        result = run_production_health_check(raise_on_failure=False)
        assert 'structure_editor' in result

    def test_atomic_refactor_check_present(self):
        from backend.engine.tools.health_check import run_production_health_check

        result = run_production_health_check(raise_on_failure=False)
        assert 'atomic_refactor' in result

    def test_check_structure_editor_returns_bool_and_str(self):
        from backend.engine.tools.health_check import (
            check_structure_editor_dependencies,
        )

        success, msg = check_structure_editor_dependencies()
        assert isinstance(success, bool)
        assert isinstance(msg, str)

    def test_check_atomic_refactor_returns_bool_and_str(self):
        from backend.engine.tools.health_check import check_atomic_refactor_dependencies

        success, msg = check_atomic_refactor_dependencies()
        assert isinstance(success, bool)
        assert isinstance(msg, str)

    def test_no_critical_failures_means_healthy(self):
        from backend.engine.tools.health_check import run_production_health_check

        with (
            patch(
                'backend.engine.tools.health_check.check_structure_editor_dependencies',
                return_value=(True, 'ok'),
            ),
            patch(
                'backend.engine.tools.health_check.check_atomic_refactor_dependencies',
                return_value=(True, 'ok'),
            ),
        ):
            result = run_production_health_check(raise_on_failure=False)
        assert result['overall_status'] == 'HEALTHY'

    def test_critical_failure_raises_when_requested(self):
        from backend.engine.tools.health_check import run_production_health_check

        with (
            patch(
                'backend.engine.tools.health_check.check_structure_editor_dependencies',
                return_value=(False, 'missing'),
            ),
            patch(
                'backend.engine.tools.health_check.check_atomic_refactor_dependencies',
                return_value=(True, 'ok'),
            ),
        ):
            with pytest.raises(RuntimeError, match='health check failed'):
                run_production_health_check(raise_on_failure=True)

    def test_critical_failure_no_raise_returns_critical(self):
        from backend.engine.tools.health_check import run_production_health_check

        with (
            patch(
                'backend.engine.tools.health_check.check_structure_editor_dependencies',
                return_value=(False, 'missing'),
            ),
            patch(
                'backend.engine.tools.health_check.check_atomic_refactor_dependencies',
                return_value=(True, 'ok'),
            ),
        ):
            result = run_production_health_check(raise_on_failure=False)
        assert result['overall_status'] == 'CRITICAL_FAILURE'
