"""Unit tests for observation orient result helpers."""

from __future__ import annotations

import pytest

from backend.cli.event_rendering.observations.exploration import _ObsExplorationMixin
from backend.cli.event_rendering.observations.mcp import _ObsMcpMixin


class TestOrientLspResult:
    @pytest.mark.parametrize(
        ('available', 'content', 'expected'),
        [
            (False, 'x', 'unavailable'),
            (True, '   ', None),
            (True, '{"definitions": []}', None),
            (True, '{"definitions": [1]}', '1 definition'),
            (True, '{"references": [1, 2]}', '2 references'),
            (True, '{"hover": {}}', 'completed'),
            (True, '{"symbols": ["a", "b"]}', '2 symbols'),
            (True, '{"issues": []}', 'clean'),
            (True, '{"issues": [1]}', '1 issue'),
            (True, '{"actions": [1, 2, 3]}', '3 actions'),
            (True, '[1, 2]', '2 results'),
            (True, 'not-json\nline2', '2 results'),
            (True, 'not-json', '1 results'),
        ],
    )
    def test_orient_lsp_result(
        self, available: bool, content: str, expected: str | None
    ) -> None:
        assert (
            _ObsExplorationMixin._orient_lsp_result(available=available, content=content)
            == expected
        )


class TestOrientGrepResult:
    @pytest.mark.parametrize(
        ('output_mode', 'match_count', 'file_count', 'error', 'expected'),
        [
            ('files_with_matches', 0, 2, None, '2 files'),
            ('count', 3, 0, None, '3 matches'),
            ('content', 1, 2, None, '1 match · 2 files'),
            ('content', 0, 0, None, 'no matches'),
            ('other', 0, 0, 'disk full', 'failed · disk full'),
        ],
    )
    def test_orient_grep_result(
        self,
        output_mode: str,
        match_count: int,
        file_count: int,
        error: str | None,
        expected: str,
    ) -> None:
        assert (
            _ObsExplorationMixin._orient_grep_result(
                query='x',
                content='',
                match_count=match_count,
                file_count=file_count,
                output_mode=output_mode,
                error=error,
            )
            == expected
        )


class TestOrientGlobAndFindSymbols:
    def test_orient_glob_result(self) -> None:
        assert (
            _ObsExplorationMixin._orient_glob_result(
                content='', file_count=0, error=None
            )
            == 'no files'
        )
        assert (
            _ObsExplorationMixin._orient_glob_result(
                content='', file_count=1, error='x'
            )
            == 'failed · x'
        )

    def test_orient_find_symbols_result(self) -> None:
        assert (
            _ObsExplorationMixin._orient_find_symbols_result(candidates=[], error=None)
            == 'no symbols'
        )
        assert (
            _ObsExplorationMixin._orient_find_symbols_result(
                candidates=[{'path': 'a.py'}, {'path': 'b.py'}],
                error=None,
            )
            == '2 symbols · 2 files'
        )


class TestOrientReadSymbolsAndAnalyze:
    def test_orient_read_symbols_result(self) -> None:
        assert (
            _ObsExplorationMixin._orient_read_symbols_result(
                available=False, content='x'
            )
            == 'unavailable'
        )
        content = 'resolved foo -> bar\nambiguous x ~> y\nnot found z'
        assert (
            _ObsExplorationMixin._orient_read_symbols_result(
                available=True, content=content
            )
            == '1 resolved · 1 ambiguous · 1 not found'
        )

    def test_orient_analyze_result(self) -> None:
        assert (
            _ObsExplorationMixin._orient_analyze_result(available=False, content='x')
            == 'unavailable'
        )
        assert (
            _ObsExplorationMixin._orient_analyze_result(available=True, content='  ')
            == 'no output'
        )
        callers = 'Callers of foo\npkg/mod.py::bar()'
        assert 'callers' in _ObsExplorationMixin._orient_analyze_result(
            available=True, content=callers
        )
        deps = 'dependency graph\npkg <- other\nimport os'
        assert 'deps' in _ObsExplorationMixin._orient_analyze_result(
            available=True, content=deps
        )
        symbols = '# comment\nsymbol Foo\nsymbol Bar'
        assert 'symbols' in _ObsExplorationMixin._orient_analyze_result(
            available=True, content=symbols
        )
        assert (
            _ObsExplorationMixin._orient_analyze_result(
                available=True, content='file_outline complete'
            )
            == 'completed'
        )


class TestOrientGrepGlobExtended:
    @pytest.mark.parametrize(
        ('output_mode', 'match_count', 'file_count', 'expected'),
        [
            ('files_with_matches', 0, 0, 'no matches'),
            ('count', 1, 0, '1 match'),
            ('', 2, 0, '2 matches'),
        ],
    )
    def test_orient_grep_result_more_modes(
        self, output_mode: str, match_count: int, file_count: int, expected: str
    ) -> None:
        assert (
            _ObsExplorationMixin._orient_grep_result(
                query='x',
                content='',
                match_count=match_count,
                file_count=file_count,
                output_mode=output_mode,
                error=None,
            )
            == expected
        )

    def test_orient_glob_and_find_symbols(self) -> None:
        assert (
            _ObsExplorationMixin._orient_glob_result(
                content='', file_count=3, error=None
            )
            == '3 files'
        )
        assert (
            _ObsExplorationMixin._orient_find_symbols_result(
                candidates=[{'path': 'a.py'}],
                error=None,
            )
            == '1 symbol'
        )


class TestOrientMcpResult:
    @pytest.mark.parametrize(
        ('name', 'content', 'expected'),
        [
            ('web_search', '', None),
            ('web_search', '{"error": true}', 'failed'),
            ('web_search', '{"count": 0}', 'no results'),
            ('web_search', '{"count": 4}', '4 results'),
            ('web_search', '{"items": [1, 2]}', '2 results'),
            ('web_search', '[1, 2, 3]', '3 results'),
            ('web_search', 'not json', None),
        ],
    )
    def test_orient_mcp_result(self, name: str, content: str, expected: str | None) -> None:
        assert _ObsMcpMixin._orient_mcp_result(name, content) == expected
