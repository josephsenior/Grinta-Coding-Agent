"""Tests for backend.cli.display.tool_call_display."""

import json
import unittest

from backend.cli.display.tool_call_display import (
    contains_tool_transport_markup,
    extract_tool_calls_from_text_markers,
    flatten_tool_call_for_history,
    format_tool_invocation_line,
    looks_like_streaming_tool_arguments,
    mcp_result_user_preview,
    redact_streamed_tool_call_markers,
    streaming_args_hint,
    summarize_tool_arguments,
    tool_headline,
    try_format_message_as_tool_json,
)


class TestToolCallDisplay(unittest.TestCase):
    def test_summarize_bash(self) -> None:
        s = summarize_tool_arguments('execute_bash', {'command': 'git status --short'})
        self.assertIn('git status', s)
        self.assertTrue(s.startswith('$'))

    def test_summarize_mcp_gateway(self) -> None:
        s = summarize_tool_arguments(
            'call_mcp_tool', {'tool_name': 'filesystem', 'arguments': {}}
        )
        self.assertIn('filesystem', s)

    def test_summarize_terminal_manager_open(self) -> None:
        s = summarize_tool_arguments(
            'terminal_manager',
            {
                'action': 'open',
                'command': 'pytest -q',
                'cwd': '/project/space/proj',
            },
        )
        self.assertIn('open', s)
        self.assertIn('pytest', s)
        self.assertIn('cwd', s)
        self.assertNotIn('open · $', s)

    def test_summarize_terminal_manager_read(self) -> None:
        s = summarize_tool_arguments(
            'terminal_manager',
            {'action': 'read', 'session_id': 'sess-abc-123'},
        )
        self.assertIn('read', s)
        self.assertIn('sess-abc-123', s)

    def test_streaming_hint_terminal_open_partial(self) -> None:
        h = streaming_args_hint(
            'terminal_manager',
            '{"action": "open", "command": "npm test',
        )
        self.assertIn('open', h)
        h2 = streaming_args_hint(
            'terminal_manager',
            '{"action": "open", "command": "npm test", "cwd": "x"}',
        )
        self.assertIn('npm test', h2)

    def test_format_invocation_line(self) -> None:
        icon, line = format_tool_invocation_line(
            'execute_bash',
            {'command': 'npm test', 'cwd': 'x'},
        )
        self.assertIsInstance(icon, str)
        self.assertIn('npm test', line)
        self.assertNotIn('{', line)

    def test_streaming_args_hint_partial(self) -> None:
        h = streaming_args_hint(
            'execute_bash',
            '{"command": "npm test',
        )
        self.assertIn('npm', h)

    def test_looks_like_tool_args(self) -> None:
        self.assertTrue(looks_like_streaming_tool_arguments('  {"command": "ls"}'))
        self.assertFalse(looks_like_streaming_tool_arguments('Hello {'))

    def test_redact_streamed_tool_call_markers(self) -> None:
        raw = '[Tool call] execute_bash({"command":"pwd"})'
        self.assertEqual(redact_streamed_tool_call_markers(raw).strip(), '')

    def test_redact_removes_bracket_tool_transport(self) -> None:
        raw = (
            '[END_TOOL_CALL]\n\n'
            '[EDIT_DIFF] --- raftkv/rpc.py +++ raftkv/rpc.py\n'
            '@@ -1 +1 @@\n'
            '-old\n'
            '+new\n\n'
            'Edit applied.'
        )
        out = redact_streamed_tool_call_markers(raw)
        self.assertNotIn('[END_TOOL_CALL]', out)
        self.assertNotIn('[EDIT_DIFF]', out)
        self.assertNotIn('--- raftkv/rpc.py', out)
        self.assertEqual(out.strip(), 'Edit applied.')

    def test_redact_removes_minimax_split_tool_transport(self) -> None:
        raw = (
            'Checking the file now.'
            ']<]minimax[>[<tool_call>\n'
            ']<]minimax[>[<invoke name="execute_powershell">\n'
            '<parameter name="command">pwd</parameter>\n'
            '[END_TOOL_CALL]'
        )
        out = redact_streamed_tool_call_markers(raw)
        self.assertEqual(out.strip(), 'Checking the file now.')
        self.assertNotIn('minimax', out)
        self.assertNotIn('<invoke', out)
        self.assertNotIn('[END_TOOL_CALL]', out)

    def test_extracts_minimax_invoke_tool_call(self) -> None:
        raw = (
            ']<]minimax[>[<tool_call>\n'
            '<invoke name="execute_powershell">\n'
            '<parameter name="command">pwd</parameter>\n'
            '<parameter name="security_risk">LOW</parameter>\n'
            '</invoke>\n'
            '</minimax:tool_call>'
        )
        calls = extract_tool_calls_from_text_markers(raw)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['function']['name'], 'execute_powershell')
        args = json.loads(calls[0]['function']['arguments'])
        self.assertEqual(args['command'], 'pwd')
        self.assertEqual(args['security_risk'], 'LOW')

    def test_contains_tool_transport_markup_covers_shared_shapes(self) -> None:
        samples = [
            '[END_TOOL_CALL]',
            '[Tool call] read({"path":"a.py"})',
            ']<]minimax[>[<tool_call>',
            '<tool_call name="read">{"path":"a.py"}</tool_call>',
            '<invoke name="read"><parameter name="path">a.py</parameter></invoke>',
            '<function=read><parameter=path>a.py</parameter></function>',
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(contains_tool_transport_markup(sample))
        self.assertFalse(contains_tool_transport_markup('plain final answer'))

    def test_strip_tool_call_marker_lines_keeps_json_shape(self) -> None:
        raw = '[Tool call] execute_bash({"command":"pwd"})'

    def test_redact_removes_friendly_tool_call_lines(self) -> None:
        friendly = flatten_tool_call_for_history(
            'execute_bash',
            '{"command":"npm test"}',
        )
        raw = f'Intro line.\n{friendly}\n\nHello.'
        out = redact_streamed_tool_call_markers(raw).strip()
        self.assertIn('Intro line.', out)
        self.assertIn('Hello.', out)
        self.assertNotIn('[Tool call]', out)

    def test_redact_removes_tool_result_protocol_blocks(self) -> None:
        raw = (
            'Done.\n\n'
            '[Tool result from execute_bash]\n'
            '[CMD_OUTPUT exit=0]\n'
            '[Below is the output of the previous command.]\n'
            '.eslintrc.cjs\n'
            'src/\n\n'
            'Next.'
        )
        out = redact_streamed_tool_call_markers(raw)
        self.assertIn('Done.', out)
        self.assertIn('Next.', out)
        self.assertNotIn('[Tool result from', out)
        self.assertNotIn('[CMD_OUTPUT', out)
        self.assertNotIn('.eslintrc.cjs', out)

    def test_flatten_tool_call_for_history_no_raw_json(self) -> None:
        line = flatten_tool_call_for_history(
            'execute_bash',
            '{"command":"npm test"}',
        )
        self.assertNotIn('{', line)
        self.assertIn('npm test', line)
        self.assertTrue(line.startswith('[Tool call]'))

    def test_mcp_result_user_preview_extracts_text(self) -> None:
        s = mcp_result_user_preview('{"text": "hello world", "meta": 1}')
        self.assertIn('hello world', s)

    def test_try_format_message_tool_json(self) -> None:
        payload = (
            '{"tool_calls":[{"id":"1","type":"function",'
            '"function":{"name":"execute_bash","arguments":"{\\"command\\": \\"pwd\\"}"}}]}'
        )
        got = try_format_message_as_tool_json(payload)
        if got is None:
            self.fail('expected formatted tool JSON')
        icon, text = got
        self.assertIsInstance(icon, str)
        self.assertIn('pwd', text)
        self.assertNotIn('tool_calls', text)

    def test_try_format_message_tool_json_no_icons(self) -> None:
        payload = (
            '{"tool_calls":[{"id":"1","type":"function",'
            '"function":{"name":"execute_bash","arguments":"{\\"command\\": \\"pwd\\"}"}}]}'
        )
        got = try_format_message_as_tool_json(payload, use_icons=False)
        if got is None:
            self.fail('expected formatted tool JSON')
        icon, text = got
        self.assertEqual(icon, '')
        self.assertIn('pwd', text)
        self.assertNotIn('⚡', text)

    def test_tool_headline_respects_use_icons(self) -> None:
        em, label = tool_headline('execute_bash', use_icons=True)
        self.assertEqual(em, '')
        self.assertEqual(label, 'Shell')
        em2, label2 = tool_headline('execute_bash', use_icons=False)
        self.assertEqual(em2, '')
        self.assertEqual(label2, 'Shell')


if __name__ == '__main__':
    unittest.main()
