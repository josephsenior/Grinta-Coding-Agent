"""Tests for silent-drop marker fixes in secondary tool outputs.

Covers:
  - Issue #2: memory recall excerpt 500-char slice now emits […truncated]
  - Issue #3: find_symbols 200-path cap now emits scope_truncated in payload
  - Issue #4: APS symbols 100-symbol cap now emits … (truncated)
  - Issue #5: APS helper line slices now emit … (truncated)
  - Issue #6: symbol preview 240-char slice now emits […]
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Issue #2: memory recall excerpt marker
# ---------------------------------------------------------------------------
class TestMemoryRecallTruncationMarker:
    def test_long_excerpt_gets_truncated_marker(self):
        from backend.engine.tools._tool_handlers import (
            _semantic_recall_registry,
            execute_memory_recall,
        )
        from backend.ledger.action import MemoryRecallAction

        long_excerpt = 'A' * 600
        _semantic_recall_registry['fn'] = lambda q, n: [
            {'excerpt': long_excerpt, 'role': 'user', 'score': 0.9},
        ]
        try:
            action = MemoryRecallAction(query='test')
            obs = execute_memory_recall(action)
            assert '[…truncated]' in obs.content
            assert obs.content.count('A') == 500
        finally:
            _semantic_recall_registry.pop('fn', None)

    def test_short_excerpt_has_no_marker(self):
        from backend.engine.tools._tool_handlers import (
            _semantic_recall_registry,
            execute_memory_recall,
        )
        from backend.ledger.action import MemoryRecallAction

        _semantic_recall_registry['fn'] = lambda q, n: [
            {'excerpt': 'short content', 'role': 'user', 'score': 0.9},
        ]
        try:
            action = MemoryRecallAction(query='test')
            obs = execute_memory_recall(action)
            assert '[…truncated]' not in obs.content
        finally:
            _semantic_recall_registry.pop('fn', None)


# ---------------------------------------------------------------------------
# Issue #3: find_symbols scope_truncated signal
# ---------------------------------------------------------------------------
class TestFindSymbolsScopeTruncated:
    def test_scope_capped_flag_when_over_200_files(self):
        from backend.engine.tools._file_ops import (
            _candidate_paths_for_symbol_search,
        )

        fake_paths = [Path(f'src/file_{i}.py') for i in range(300)]

        with patch(
            'backend.engine.tools._file_ops._workspace_root', return_value=Path('.')
        ):
            with patch.object(Path, 'rglob', return_value=iter(fake_paths)):
                with patch.object(Path, 'is_file', return_value=True):
                    with patch.object(
                        Path,
                        'suffix',
                        new_callable=lambda: property(lambda self: '.py'),
                    ):
                        with patch.object(
                            Path,
                            'parts',
                            new_callable=lambda: property(lambda self: (str(self),)),
                        ):
                            paths, capped = _candidate_paths_for_symbol_search()
                            assert capped is True
                            assert len(paths) == 200

    def test_scope_not_capped_when_under_limit(self):
        from backend.engine.tools._file_ops import (
            _candidate_paths_for_symbol_search,
        )

        fake_paths = [Path(f'src/file_{i}.py') for i in range(50)]

        with patch(
            'backend.engine.tools._file_ops._workspace_root', return_value=Path('.')
        ):
            with patch.object(Path, 'rglob', return_value=iter(fake_paths)):
                with patch.object(Path, 'is_file', return_value=True):
                    with patch.object(
                        Path,
                        'suffix',
                        new_callable=lambda: property(lambda self: '.py'),
                    ):
                        with patch.object(
                            Path,
                            'parts',
                            new_callable=lambda: property(lambda self: (str(self),)),
                        ):
                            paths, capped = _candidate_paths_for_symbol_search()
                            assert capped is False


# ---------------------------------------------------------------------------
# Issue #4: APS symbols 100-cap marker
# ---------------------------------------------------------------------------
class TestApsSymbolsTruncationMarker:
    def test_symbols_emits_truncated_marker_over_100(self, tmp_path):
        from backend.engine.tools._aps_tree import _build_symbols_action

        f = tmp_path / 'big.py'
        lines = []
        for i in range(150):
            lines.append(f'def func_{i}(): pass')
        f.write_text('\n'.join(lines))

        result = _build_symbols_action(str(f))
        assert '… (truncated)' in result
        assert result.count('def func_') == 100

    def test_symbols_no_marker_under_100(self, tmp_path):
        from backend.engine.tools._aps_tree import _build_symbols_action

        f = tmp_path / 'small.py'
        f.write_text('def foo(): pass\ndef bar(): pass\n')

        result = _build_symbols_action(str(f))
        assert '… (truncated)' not in result


# ---------------------------------------------------------------------------
# Issue #5: APS helper line-slice markers
# ---------------------------------------------------------------------------
class TestApsHelperSliceMarkers:
    def test_aps_shared_reverse_imports_marker(self):
        from backend.engine.tools._aps_shared import _imports_reverse_via_rg

        mock_result = MagicMock()
        mock_result.stdout = '\n'.join(f'file_{i}.py' for i in range(40))
        mock_result.returncode = 0

        with patch(
            'backend.engine.tools._aps_shared.shutil.which', return_value='/usr/bin/rg'
        ):
            with patch(
                'backend.engine.tools._aps_shared._run_command',
                return_value=mock_result,
            ):
                result = _imports_reverse_via_rg('test_module')
                assert result is not None
                assert '… (truncated)' in result
                assert len(result) == 31  # 30 lines + marker

    def test_aps_callers_coverage_marker(self):
        from backend.engine.tools._aps_callers_coverage import _callers_lines_via_rg

        mock_result = MagicMock()
        mock_result.stdout = '\n'.join(f'hit_{i}' for i in range(60))
        mock_result.returncode = 0

        with patch(
            'backend.engine.tools._aps_callers_coverage.shutil.which',
            return_value='/usr/bin/rg',
        ):
            with patch(
                'backend.engine.tools._aps_callers_coverage._run_command',
                return_value=mock_result,
            ):
                result = _callers_lines_via_rg('symbol', '.')
                assert result is not None
                assert '… (truncated)' in result
                assert len(result) == 51  # 50 lines + marker


# ---------------------------------------------------------------------------
# Issue #6: symbol preview 240-char marker
# ---------------------------------------------------------------------------
class TestSymbolPreviewMarker:
    def test_long_preview_gets_ellipsis(self):
        from backend.engine.tools._file_ops import _symbol_preview

        long_line = 'x' * 300
        content = f'{long_line}\nsecond\nthird\n'
        preview = _symbol_preview(content, 1, 3)
        assert '[…]' in preview
        assert len(preview) == 243  # 240 + '[…]' (3 chars)

    def test_short_preview_has_no_marker(self):
        from backend.engine.tools._file_ops import _symbol_preview

        content = 'def foo():\n    pass\n'
        preview = _symbol_preview(content, 1, 2)
        assert '[…]' not in preview


# ---------------------------------------------------------------------------
# MCP output truncation (execution-layer cap)
# ---------------------------------------------------------------------------
class TestMcpOutputTruncation:
    def test_short_mcp_output_not_truncated(self):
        from backend.integrations.mcp.mcp_utils import _truncate_mcp_output

        content = '{"result": "ok"}'
        assert _truncate_mcp_output(content, 1000) == content

    def test_long_mcp_output_truncated_with_marker(self):
        from backend.integrations.mcp.mcp_utils import _truncate_mcp_output

        content = 'x' * 50000
        result = _truncate_mcp_output(content, 1000)
        assert '[APP: MCP output truncated' in result
        assert len(result) < len(content)
        assert result.startswith('x' * 500)
        assert result.endswith('x' * 500)

    def test_mcp_truncation_respects_env_var(self):
        from backend.integrations.mcp.mcp_utils import _truncate_mcp_output

        with patch.dict('os.environ', {'APP_MAX_MCP_OUTPUT_CHARS': '200'}):
            content = 'x' * 500
            result = _truncate_mcp_output(content)
            assert '[APP: MCP output truncated' in result
            assert len(result) < len(content)

    def test_mcp_truncation_zero_cap_means_no_limit(self):
        from backend.integrations.mcp.mcp_utils import _truncate_mcp_output

        content = 'x' * 50000
        assert _truncate_mcp_output(content, 0) == content


# ---------------------------------------------------------------------------
# TerminalObservation dropped_chars marker
# ---------------------------------------------------------------------------
class TestTerminalDroppedCharsMarker:
    def test_dropped_chars_surfaces_warning(self):
        from backend.context.processors.observation_processors import (
            convert_observation_to_message,
        )
        from backend.ledger.observation import TerminalObservation

        obs = TerminalObservation(
            session_id='test-session',
            content='some terminal output',
            dropped_chars=5000,
        )
        msg = convert_observation_to_message(obs, max_message_chars=10000)
        text = msg.content[0].text if msg.content else ''
        assert '5000 chars were dropped' in text
        assert 'terminal ring buffer' in text

    def test_zero_dropped_chars_no_warning(self):
        from backend.context.processors.observation_processors import (
            convert_observation_to_message,
        )
        from backend.ledger.observation import TerminalObservation

        obs = TerminalObservation(
            session_id='test-session',
            content='some terminal output',
            dropped_chars=0,
        )
        msg = convert_observation_to_message(obs, max_message_chars=10000)
        text = msg.content[0].text if msg.content else ''
        assert 'dropped' not in text.lower()

    def test_none_dropped_chars_no_warning(self):
        from backend.context.processors.observation_processors import (
            convert_observation_to_message,
        )
        from backend.ledger.observation import TerminalObservation

        obs = TerminalObservation(
            session_id='test-session',
            content='some terminal output',
            dropped_chars=None,
        )
        msg = convert_observation_to_message(obs, max_message_chars=10000)
        text = msg.content[0].text if msg.content else ''
        assert 'dropped' not in text.lower()


# ---------------------------------------------------------------------------
# Ripgrep byte-truncation warning (bounded_io silent drop)
# ---------------------------------------------------------------------------
class TestRipgrepTruncationWarning:
    def test_truncated_result_emits_warning(self):
        from backend.core.bounded_result import BoundedResult
        from backend.engine.tools._search_helpers import (
            get_ripgrep_truncation_warning,
        )

        result = BoundedResult(
            stdout='x' * 100,
            stderr='',
            returncode=0,
            truncated=True,
            timed_out=False,
        )
        warning = get_ripgrep_truncation_warning(result)
        assert 'ripgrep output exceeded' in warning
        assert '2 MiB' in warning

    def test_non_truncated_result_no_warning(self):
        from backend.core.bounded_result import BoundedResult
        from backend.engine.tools._search_helpers import (
            get_ripgrep_truncation_warning,
        )

        result = BoundedResult(
            stdout='x' * 100,
            stderr='',
            returncode=0,
            truncated=False,
            timed_out=False,
        )
        assert get_ripgrep_truncation_warning(result) == ''


# ---------------------------------------------------------------------------
# Web fetch fallback truncation
# ---------------------------------------------------------------------------
class TestWebFetchFallbackTruncation:
    def test_truncate_fetch_payload_text_caps_long_content(self):
        from backend.engine.tools.web_tools import _truncate_fetch_payload_text

        payload = {
            'ok': True,
            'content': [{'type': 'text', 'text': 'A' * 10000}],
        }
        result = _truncate_fetch_payload_text(payload, 1000)
        text = result['content'][0]['text']
        assert len(text) < 10000
        assert '[... truncated:' in text

    def test_truncate_fetch_payload_text_preserves_short_content(self):
        from backend.engine.tools.web_tools import _truncate_fetch_payload_text

        payload = {
            'ok': True,
            'content': [{'type': 'text', 'text': 'short content'}],
        }
        result = _truncate_fetch_payload_text(payload, 1000)
        assert result['content'][0]['text'] == 'short content'

    def test_truncate_fetch_payload_text_handles_non_list_content(self):
        from backend.engine.tools.web_tools import _truncate_fetch_payload_text

        payload = {'ok': True, 'content': 'raw string'}
        result = _truncate_fetch_payload_text(payload, 1000)
        assert result['content'] == 'raw string'
