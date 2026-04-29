"""Tests for backend.cli._tool_display submodules (headline, summarize, redact, preview)."""

from __future__ import annotations

import unittest

# ============================================================================
# headline.py
# ============================================================================
from backend.cli._tool_display.headline import (
    friendly_verb_for_tool,
    tool_activity_stats_hint,
    tool_headline,
)


class TestToolHeadline(unittest.TestCase):
    def test_known_tool(self) -> None:
        _, label = tool_headline('execute_bash')
        self.assertEqual(label, 'Shell')

    def test_unknown_tool_title_cased(self) -> None:
        _, label = tool_headline('my_custom_tool')
        self.assertEqual(label, 'My Custom Tool')

    def test_empty_tool_name(self) -> None:
        _, label = tool_headline('')
        self.assertEqual(label, 'Tool')

    def test_icon_always_empty(self) -> None:
        icon, _ = tool_headline('execute_bash', use_icons=True)
        self.assertEqual(icon, '')


class TestFriendlyVerbForTool(unittest.TestCase):
    def test_text_editor_read(self) -> None:
        v = friendly_verb_for_tool('text_editor', {'command': 'read_file'})
        self.assertEqual(v, 'Viewed')

    def test_text_editor_create(self) -> None:
        v = friendly_verb_for_tool('text_editor', {'command': 'create_file'})
        self.assertEqual(v, 'Created')

    def test_text_editor_insert(self) -> None:
        v = friendly_verb_for_tool('text_editor', {'command': 'insert_text'})
        self.assertEqual(v, 'Inserted')

    def test_text_editor_undo(self) -> None:
        v = friendly_verb_for_tool('text_editor', {'command': 'undo_last_edit'})
        self.assertEqual(v, 'Reverted')

    def test_text_editor_unknown_command(self) -> None:
        v = friendly_verb_for_tool('text_editor', {'command': 'unknown_cmd'})
        self.assertEqual(v, 'Edited')

    def test_execute_bash(self) -> None:
        v = friendly_verb_for_tool('execute_bash', {})
        self.assertEqual(v, 'Ran')

    def test_execute_powershell(self) -> None:
        v = friendly_verb_for_tool('execute_powershell', {})
        self.assertEqual(v, 'Ran')

    def test_terminal_manager_open(self) -> None:
        v = friendly_verb_for_tool('terminal_manager', {'action': 'open'})
        self.assertEqual(v, 'Started')

    def test_terminal_manager_input(self) -> None:
        v = friendly_verb_for_tool('terminal_manager', {'action': 'input'})
        self.assertEqual(v, 'Sent')

    def test_terminal_manager_read(self) -> None:
        v = friendly_verb_for_tool('terminal_manager', {'action': 'read'})
        self.assertEqual(v, 'Read')

    def test_terminal_manager_unknown_action(self) -> None:
        # Falls back to title-cased tool name
        v = friendly_verb_for_tool('terminal_manager', {'action': 'whatever'})
        self.assertEqual(v, 'Terminal Manager')

    def test_simple_map_tools(self) -> None:
        self.assertEqual(friendly_verb_for_tool('search_code', {}), 'Searched')
        self.assertEqual(friendly_verb_for_tool('think', {}), 'Thinking')
        self.assertEqual(friendly_verb_for_tool('finish', {}), 'Finished')
        self.assertEqual(friendly_verb_for_tool('checkpoint', {}), 'Saved')

    def test_empty_tool_name(self) -> None:
        v = friendly_verb_for_tool('', {})
        self.assertEqual(v, 'Tool')

    def test_unknown_tool_title_case(self) -> None:
        v = friendly_verb_for_tool('my_new_tool', {})
        self.assertEqual(v, 'My New Tool')


class TestToolActivityStatsHint(unittest.TestCase):
    def test_search_code_with_path(self) -> None:
        hint = tool_activity_stats_hint('search_code', {'path': '/src'})
        self.assertIn('/src', hint)

    def test_search_code_no_path(self) -> None:
        hint = tool_activity_stats_hint('search_code', {})
        self.assertIsNone(hint)

    def test_analyze_project_with_depth(self) -> None:
        hint = tool_activity_stats_hint('analyze_project_structure', {'depth': 3})
        self.assertIn('3', hint)

    def test_analyze_project_with_path(self) -> None:
        hint = tool_activity_stats_hint('analyze_project_structure', {'path': '/mydir'})
        self.assertIn('/mydir', hint)

    def test_explore_tree_with_depth(self) -> None:
        hint = tool_activity_stats_hint('explore_tree_structure', {'max_depth': 5})
        self.assertIn('5', hint)

    def test_explore_tree_no_depth(self) -> None:
        hint = tool_activity_stats_hint('explore_tree_structure', {})
        self.assertIsNone(hint)

    def test_text_editor_read_with_range(self) -> None:
        hint = tool_activity_stats_hint('text_editor', {
            'command': 'read_file',
            'path': 'foo.py',
            'view_range_start': 10,
            'view_range_end': 20,
        })
        self.assertIsNotNone(hint)
        self.assertIn('10', hint)

    def test_text_editor_replace_with_path(self) -> None:
        hint = tool_activity_stats_hint('text_editor', {
            'command': 'replace_text',
            'path': 'myfile.py',
        })
        self.assertIsNotNone(hint)

    def test_task_tracker_with_list(self) -> None:
        hint = tool_activity_stats_hint('task_tracker', {
            'task_list': [{'title': 'A'}, {'title': 'B'}],
        })
        self.assertIsNotNone(hint)
        self.assertIn('2', hint)

    def test_task_tracker_empty_list(self) -> None:
        hint = tool_activity_stats_hint('task_tracker', {'task_list': []})
        self.assertIsNone(hint)

    def test_read_symbol_with_name(self) -> None:
        hint = tool_activity_stats_hint('read_symbol_definition', {'symbol': 'MyClass'})
        self.assertIn('MyClass', hint)

    def test_terminal_manager_stats(self) -> None:
        hint = tool_activity_stats_hint('terminal_manager', {
            'action': 'read',
            'session_id': 'sess-abc',
        })
        self.assertIsNotNone(hint)
        self.assertIn('sess-abc', hint)

    def test_terminal_manager_open_no_stats(self) -> None:
        hint = tool_activity_stats_hint('terminal_manager', {
            'action': 'open',
            'session_id': 'sess-abc',
        })
        self.assertIsNone(hint)

    def test_lsp_with_command(self) -> None:
        hint = tool_activity_stats_hint('code_intelligence', {'command': 'goto_def'})
        self.assertEqual(hint, 'goto_def')

    def test_unknown_tool_returns_none(self) -> None:
        hint = tool_activity_stats_hint('some_random_tool', {'x': 1})
        self.assertIsNone(hint)


# ============================================================================
# summarize.py
# ============================================================================

from backend.cli._tool_display.summarize import (
    _arg_str,
    _pluralize_result_label,
    _preview_result_item,
    _summarize_result_collection,
    _term_input_summary,
    _term_open_summary,
    _term_read_summary,
    _trunc,
    format_tool_activity_rows,
    format_tool_invocation_line,
    parse_tool_arguments_json,
    streaming_args_hint,
    summarize_tool_arguments,
)


class TestTrunc(unittest.TestCase):
    def test_short_string_unchanged(self) -> None:
        self.assertEqual(_trunc('hello', 100), 'hello')

    def test_long_string_truncated(self) -> None:
        s = 'a' * 200
        result = _trunc(s, 100)
        self.assertEqual(len(result), 100)
        self.assertTrue(result.endswith('…'))

    def test_collapses_whitespace(self) -> None:
        self.assertEqual(_trunc('a  b   c', 100), 'a b c')


class TestPluralize(unittest.TestCase):
    def test_singular(self) -> None:
        self.assertEqual(_pluralize_result_label('results', 1), 'result')

    def test_plural(self) -> None:
        self.assertEqual(_pluralize_result_label('results', 2), 'results')

    def test_no_s_suffix(self) -> None:
        self.assertEqual(_pluralize_result_label('match', 1), 'match')
        self.assertEqual(_pluralize_result_label('match', 2), 'matchs')


class TestPreviewResultItem(unittest.TestCase):
    def test_string_item(self) -> None:
        self.assertEqual(_preview_result_item('hello', max_len=50), 'hello')

    def test_dict_with_title(self) -> None:
        result = _preview_result_item({'title': 'My Title'}, max_len=50)
        self.assertEqual(result, 'My Title')

    def test_dict_with_path(self) -> None:
        result = _preview_result_item({'path': '/foo/bar.py'}, max_len=50)
        self.assertEqual(result, '/foo/bar.py')

    def test_empty_string(self) -> None:
        self.assertEqual(_preview_result_item('', max_len=50), '')

    def test_integer_item(self) -> None:
        self.assertEqual(_preview_result_item(42, max_len=50), '')


class TestSummarizeResultCollection(unittest.TestCase):
    def test_empty_list(self) -> None:
        result = _summarize_result_collection([], label='results', max_len=100)
        self.assertIn('0', result)

    def test_one_item(self) -> None:
        result = _summarize_result_collection(['foo.py'], label='results', max_len=100)
        self.assertIn('1', result)

    def test_with_preview(self) -> None:
        result = _summarize_result_collection(
            [{'title': 'A Preview'}], label='results', max_len=100
        )
        self.assertIn('A Preview', result)


class TestArgStr(unittest.TestCase):
    def test_finds_first_key(self) -> None:
        result = _arg_str({'a': 'val_a', 'b': 'val_b'}, 'a', 'b')
        self.assertEqual(result, 'val_a')

    def test_skips_empty_string(self) -> None:
        result = _arg_str({'a': '', 'b': 'val'}, 'a', 'b')
        self.assertEqual(result, 'val')

    def test_not_found(self) -> None:
        result = _arg_str({}, 'a', 'b')
        self.assertIsNone(result)


class TestSummarizeToolArguments(unittest.TestCase):
    def test_bash(self) -> None:
        s = summarize_tool_arguments('execute_bash', {'command': 'ls -la'})
        self.assertIn('ls -la', s)

    def test_text_editor_create(self) -> None:
        s = summarize_tool_arguments('text_editor', {'command': 'create_file', 'path': 'foo.py'})
        self.assertIn('foo.py', s)
        self.assertIn('new file', s)

    def test_think(self) -> None:
        s = summarize_tool_arguments('think', {'thought': 'Plan A'})
        self.assertIn('Plan A', s)

    def test_finish(self) -> None:
        s = summarize_tool_arguments('finish', {'message': 'All done'})
        self.assertIn('All done', s)

    def test_memory_manager(self) -> None:
        s = summarize_tool_arguments('memory_manager', {'operation': 'store', 'key': 'my_key'})
        self.assertIn('store', s)

    def test_task_tracker(self) -> None:
        s = summarize_tool_arguments('task_tracker', {
            'operation': 'update',
            'task_list': [1, 2, 3],
        })
        self.assertIn('3', s)

    def test_search_code(self) -> None:
        s = summarize_tool_arguments('search_code', {'query': 'parse_args', 'path': '/src'})
        self.assertIn('parse_args', s)

    def test_code_intelligence(self) -> None:
        s = summarize_tool_arguments('code_intelligence', {'command': 'hover', 'symbol': 'Foo'})
        self.assertIn('Foo', s)

    def test_explore_tree(self) -> None:
        s = summarize_tool_arguments('explore_tree_structure', {'path': '/my/dir'})
        self.assertEqual(s, '/my/dir')

    def test_analyze_project(self) -> None:
        s = summarize_tool_arguments('analyze_project_structure', {})
        self.assertEqual(s, 'scan workspace')

    def test_apply_patch(self) -> None:
        s = summarize_tool_arguments('apply_patch', {'patch': 'diff --git a b\n...'})
        self.assertEqual(s, 'apply patch')

    def test_delegate_task(self) -> None:
        s = summarize_tool_arguments('delegate_task', {'task_description': 'do X'})
        self.assertIn('do X', s)

    def test_communicate_with_user(self) -> None:
        s = summarize_tool_arguments('communicate_with_user', {'message': 'hi'})
        self.assertIn('hi', s)

    def test_call_mcp_tool(self) -> None:
        s = summarize_tool_arguments('call_mcp_tool', {'tool_name': 'filesystem'})
        self.assertIn('filesystem', s)

    def test_checkpoint_with_label(self) -> None:
        s = summarize_tool_arguments('checkpoint', {'label': 'before refactor'})
        self.assertIn('before refactor', s)

    def test_checkpoint_no_label(self) -> None:
        s = summarize_tool_arguments('checkpoint', {})
        self.assertEqual(s, 'save state')

    def test_summarize_context(self) -> None:
        s = summarize_tool_arguments('summarize_context', {})
        self.assertEqual(s, 'compress conversation')

    def test_symbol_editor_edit_symbols(self) -> None:
        s = summarize_tool_arguments('symbol_editor', {
            'command': 'edit_symbols',
            'path': 'foo.py',
            'edits': [1, 2],
        })
        self.assertIn('2 symbols', s)

    def test_symbol_editor_other_command(self) -> None:
        s = summarize_tool_arguments('symbol_editor', {
            'command': 'rename',
            'path': 'bar.py',
        })
        self.assertIn('rename', s)

    def test_shared_task_board(self) -> None:
        s = summarize_tool_arguments('shared_task_board', {'operation': 'list'})
        self.assertEqual(s, 'list')

    def test_read_symbol_definition(self) -> None:
        s = summarize_tool_arguments('read_symbol_definition', {'symbol': 'MyClass', 'file': 'foo.py'})
        self.assertIn('MyClass', s)

    def test_verify_file_lines(self) -> None:
        s = summarize_tool_arguments('verify_file_lines', {'path': '/a/b.py'})
        self.assertIn('/a/b.py', s)

    def test_generic_fallback(self) -> None:
        s = summarize_tool_arguments('some_unknown_tool', {'message': 'info'})
        self.assertIn('info', s)

    def test_generic_no_match(self) -> None:
        s = summarize_tool_arguments('some_unknown_tool', {})
        self.assertEqual(s, '…')


class TestTerminalSummarizers(unittest.TestCase):
    def test_term_open_with_cmd_and_cwd(self) -> None:
        s = _term_open_summary({'command': 'pytest', 'cwd': '/project'})
        self.assertIn('open', s)
        self.assertIn('pytest', s)
        self.assertIn('/project', s)

    def test_term_open_no_command(self) -> None:
        s = _term_open_summary({})
        self.assertIn('open', s)

    def test_term_input_with_input(self) -> None:
        s = _term_input_summary({'input': 'yes', 'session_id': 's1'})
        self.assertIn('input', s)

    def test_term_input_with_ctrl(self) -> None:
        s = _term_input_summary({'control': 'C', 'session_id': 's1'})
        self.assertIn('ctrl', s)

    def test_term_input_empty(self) -> None:
        s = _term_input_summary({})
        self.assertIn('input', s)

    def test_term_read_with_session(self) -> None:
        s = _term_read_summary({'session_id': 'my-session'})
        self.assertIn('read', s)
        self.assertIn('my-session', s)

    def test_term_read_no_session(self) -> None:
        s = _term_read_summary({})
        self.assertIn('read', s)


class TestParseToolArgumentsJson(unittest.TestCase):
    def test_valid_json(self) -> None:
        result = parse_tool_arguments_json('{"key": "val"}')
        self.assertEqual(result, {'key': 'val'})

    def test_invalid_json(self) -> None:
        self.assertIsNone(parse_tool_arguments_json('{bad'))

    def test_empty(self) -> None:
        self.assertIsNone(parse_tool_arguments_json(''))

    def test_non_dict(self) -> None:
        self.assertIsNone(parse_tool_arguments_json('[1, 2]'))


class TestFormatToolActivityRows(unittest.TestCase):
    def test_bash(self) -> None:
        verb, detail, stats = format_tool_activity_rows('execute_bash', {'command': 'ls'})
        self.assertEqual(verb, 'Ran')
        self.assertIn('ls', detail)

    def test_vague_summary_replaced(self) -> None:
        verb, detail, _ = format_tool_activity_rows('execute_bash', {})
        # When summary is vague (command…), it gets replaced by tool name
        self.assertIsInstance(detail, str)


class TestFormatToolInvocationLine(unittest.TestCase):
    def test_known_tool_with_args(self) -> None:
        icon, line = format_tool_invocation_line('execute_bash', {'command': 'ls'})
        self.assertIn('ls', line)

    def test_empty_args(self) -> None:
        icon, line = format_tool_invocation_line('execute_bash', None)
        self.assertTrue(line.endswith('…'))


class TestStreamingArgsHint(unittest.TestCase):
    def test_complete_json(self) -> None:
        hint = streaming_args_hint('execute_bash', '{"command": "git log"}')
        self.assertIn('git log', hint)

    def test_partial_json_command(self) -> None:
        hint = streaming_args_hint('execute_bash', '{"command": "npm test')
        self.assertIn('npm test', hint)

    def test_empty(self) -> None:
        self.assertEqual(streaming_args_hint('execute_bash', ''), '')

    def test_terminal_manager_open(self) -> None:
        hint = streaming_args_hint('terminal_manager', '{"action": "open", "command": "bash"}')
        self.assertIn('open', hint)

    def test_terminal_manager_read(self) -> None:
        hint = streaming_args_hint('terminal_manager', '{"action": "read", "session_id": "sess-x"}')
        self.assertIn('read', hint)

    def test_terminal_manager_input_ctrl(self) -> None:
        hint = streaming_args_hint('terminal_manager', '{"action": "input", "control": "C"}')
        self.assertIn('ctrl', hint)


# ============================================================================
# redact.py
# ============================================================================

from backend.cli._tool_display.redact import (
    _balanced_json_object_end,
    extract_tool_calls_from_text_markers,
    redact_streamed_tool_call_markers,
    strip_protocol_echo_blocks,
    strip_tool_call_marker_lines,
)


class TestStripToolCallMarkerLines(unittest.TestCase):
    def test_no_markers(self) -> None:
        text = 'Hello world'
        self.assertEqual(strip_tool_call_marker_lines(text), 'Hello world')

    def test_keeps_json_format_tool_call_line(self) -> None:
        # Lines with [Tool call] name({...}) are actual tool calls — kept.
        text = 'before\n[Tool call] text_editor({"command":"read_file","path":"f.py"})\nafter'
        result = strip_tool_call_marker_lines(text)
        self.assertIn('[Tool call] text_editor', result)
        self.assertIn('after', result)

    def test_strips_friendly_summary_line(self) -> None:
        # Lines with [Tool call] NOT followed by name( are "friendly" summaries — dropped.
        text = 'before\n[Tool call] Viewed: foo.py\nafter'
        result = strip_tool_call_marker_lines(text)
        self.assertNotIn('[Tool call] Viewed', result)
        self.assertIn('after', result)

    def test_partial_marker_dropped(self) -> None:
        text = '[Tool call '
        result = strip_tool_call_marker_lines(text)
        self.assertEqual(result, '')


class TestStripProtocolEchoBlocks(unittest.TestCase):
    def test_no_echo(self) -> None:
        text = 'Normal response'
        self.assertEqual(strip_protocol_echo_blocks(text), text)

    def test_strips_tool_result_block(self) -> None:
        text = (
            'Done.\n\n[Tool result from execute_bash]\n[CMD_OUTPUT exit=0]\nfiles\n\nNext.'
        )
        result = strip_protocol_echo_blocks(text)
        self.assertIn('Done.', result)
        self.assertNotIn('[Tool result from', result)

    def test_empty_string(self) -> None:
        self.assertEqual(strip_protocol_echo_blocks(''), '')

    def test_no_bracket(self) -> None:
        text = 'No brackets here'
        self.assertEqual(strip_protocol_echo_blocks(text), text)


class TestBalancedJsonObjectEnd(unittest.TestCase):
    def test_simple_object(self) -> None:
        s = '{"key": "val"}'
        end = _balanced_json_object_end(s, 0)
        self.assertEqual(end, len(s))

    def test_nested_object(self) -> None:
        s = '{"a": {"b": 1}}'
        end = _balanced_json_object_end(s, 0)
        self.assertEqual(end, len(s))

    def test_unclosed_returns_none(self) -> None:
        s = '{"key": "val"'
        end = _balanced_json_object_end(s, 0)
        self.assertIsNone(end)

    def test_offset(self) -> None:
        s = 'PREFIX{"key": 1}'
        end = _balanced_json_object_end(s, 6)
        self.assertEqual(end, len(s))


class TestRedactStreamedToolCallMarkers(unittest.TestCase):
    def test_no_markers(self) -> None:
        text = 'Hello world'
        self.assertEqual(redact_streamed_tool_call_markers(text), 'Hello world')

    def test_redacts_complete_marker(self) -> None:
        text = '[Tool call] text_editor({"command": "read_file", "path": "a.py"})'
        result = redact_streamed_tool_call_markers(text)
        self.assertNotIn('[Tool call]', result)
        self.assertNotIn('text_editor', result)

    def test_keeps_surrounding_text(self) -> None:
        text = 'Before.\n[Tool call] execute_bash({"command": "ls"})\nAfter.'
        result = redact_streamed_tool_call_markers(text)
        self.assertIn('Before.', result)
        self.assertIn('After.', result)
        self.assertNotIn('[Tool call]', result)

    def test_incomplete_marker_truncated(self) -> None:
        text = 'Intro [Tool call] execute_bash({"command": "ls'
        result = redact_streamed_tool_call_markers(text)
        # Truncates at prefix
        self.assertNotIn('[Tool call]', result)

    def test_multiple_markers(self) -> None:
        text = (
            '[Tool call] execute_bash({"command": "ls"})\n'
            '[Tool call] execute_bash({"command": "pwd"})\n'
            'Done.'
        )
        result = redact_streamed_tool_call_markers(text)
        self.assertNotIn('[Tool call]', result)
        self.assertIn('Done.', result)


class TestExtractToolCallsFromTextMarkers(unittest.TestCase):
    def test_no_markers(self) -> None:
        result = extract_tool_calls_from_text_markers('no markers here')
        self.assertEqual(result, [])

    def test_single_marker(self) -> None:
        text = '[Tool call] execute_bash({"command": "ls -la"})'
        result = extract_tool_calls_from_text_markers(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['function']['name'], 'execute_bash')

    def test_multiple_markers(self) -> None:
        text = (
            '[Tool call] execute_bash({"command": "ls"})\n'
            '[Tool call] text_editor({"command": "read_file", "path": "a.py"})\n'
        )
        result = extract_tool_calls_from_text_markers(text)
        self.assertEqual(len(result), 2)
        names = [r['function']['name'] for r in result]
        self.assertIn('execute_bash', names)
        self.assertIn('text_editor', names)

    def test_arguments_preserved(self) -> None:
        text = '[Tool call] execute_bash({"command": "git status"})'
        result = extract_tool_calls_from_text_markers(text)
        self.assertEqual(len(result), 1)
        import json
        args = json.loads(result[0]['function']['arguments'])
        self.assertEqual(args['command'], 'git status')


# ============================================================================
# preview.py
# ============================================================================

from backend.cli._tool_display.preview import (
    _mcp_collection_summary,
    _mcp_count_summary,
    _mcp_error_summary,
    _mcp_search_code_summary,
    _mcp_text_field_summary,
    looks_like_streaming_tool_arguments,
)


class TestLooksLikeStreamingToolArguments(unittest.TestCase):
    def test_json_with_command(self) -> None:
        self.assertTrue(looks_like_streaming_tool_arguments('{"command": "ls"}'))

    def test_json_with_path(self) -> None:
        self.assertTrue(looks_like_streaming_tool_arguments('  {"path": "foo.py"}'))

    def test_not_starting_with_brace(self) -> None:
        self.assertFalse(looks_like_streaming_tool_arguments('hello {"command": "ls"}'))

    def test_no_known_markers(self) -> None:
        self.assertFalse(looks_like_streaming_tool_arguments('{"unknown": 1}'))


class TestMcpCountSummary(unittest.TestCase):
    def test_total_count(self) -> None:
        result = _mcp_count_summary({'total_count': 5, 'query': 'foo'})
        self.assertIsNotNone(result)
        self.assertIn('5', result)
        self.assertIn('foo', result)

    def test_count_key(self) -> None:
        result = _mcp_count_summary({'count': 3})
        self.assertIsNotNone(result)
        self.assertIn('3', result)

    def test_no_count(self) -> None:
        result = _mcp_count_summary({'something': 'else'})
        self.assertIsNone(result)


class TestMcpSearchCodeSummary(unittest.TestCase):
    def test_search_code_in_content(self) -> None:
        result = _mcp_search_code_summary({'results': ['a', 'b']}, 'search_code result')
        self.assertIsNotNone(result)
        self.assertIn('2', result)

    def test_tool_name_is_search_code(self) -> None:
        result = _mcp_search_code_summary({'tool_name': 'search_code', 'total_count': 7}, '')
        self.assertIsNotNone(result)
        self.assertIn('7', result)

    def test_no_match(self) -> None:
        result = _mcp_search_code_summary({}, 'some other content')
        self.assertIsNone(result)


class TestMcpCollectionSummary(unittest.TestCase):
    def test_results_list(self) -> None:
        result = _mcp_collection_summary({'results': ['a', 'b', 'c']}, max_len=100)
        self.assertIsNotNone(result)
        self.assertIn('3', result)

    def test_items_list(self) -> None:
        result = _mcp_collection_summary({'items': ['x']}, max_len=100)
        self.assertIsNotNone(result)

    def test_no_collection(self) -> None:
        result = _mcp_collection_summary({'message': 'hello'}, max_len=100)
        self.assertIsNone(result)


class TestMcpTextFieldSummary(unittest.TestCase):
    def test_text_field(self) -> None:
        result = _mcp_text_field_summary({'text': 'hello world'}, max_len=100)
        self.assertIsNotNone(result)
        self.assertIn('hello', result)

    def test_message_field(self) -> None:
        result = _mcp_text_field_summary({'message': 'task complete'}, max_len=100)
        self.assertIsNotNone(result)

    def test_list_value(self) -> None:
        result = _mcp_text_field_summary({'text': ['a', 'b']}, max_len=100)
        self.assertIsNotNone(result)

    def test_dict_value(self) -> None:
        result = _mcp_text_field_summary({'text': {'key': 'val'}}, max_len=100)
        self.assertIsNotNone(result)

    def test_no_text_field(self) -> None:
        result = _mcp_text_field_summary({'other': 'value'}, max_len=100)
        self.assertIsNone(result)


class TestMcpErrorSummary(unittest.TestCase):
    def test_error_string(self) -> None:
        result = _mcp_error_summary({'error': 'not found'}, max_len=100)
        self.assertIsNotNone(result)
        self.assertIn('not found', result)

    def test_error_dict_with_message(self) -> None:
        result = _mcp_error_summary({'error': {'message': 'bad request'}}, max_len=100)
        self.assertIsNotNone(result)

    def test_no_error(self) -> None:
        result = _mcp_error_summary({'status': 'ok'}, max_len=100)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
