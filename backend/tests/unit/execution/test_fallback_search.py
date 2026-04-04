"""Tests for backend.execution.utils.fallbacks.search module.

Targets 0% coverage (65 statements).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.execution.utils.fallbacks.search import PythonSearcher
from backend.utils.regex_limits import MAX_USER_REGEX_PATTERN_CHARS


@pytest.fixture()
def searcher() -> PythonSearcher:
    return PythonSearcher()


@pytest.fixture()
def case_insensitive_searcher() -> PythonSearcher:
    return PythonSearcher(case_sensitive=False)


@pytest.fixture()
def tmp_tree(tmp_path: Path) -> Path:
    """Create a small file tree for search testing."""
    (tmp_path / 'hello.py').write_text("def hello():\n    return 'world'\n")
    (tmp_path / 'readme.md').write_text('# README\nThis is a project\n')
    sub = tmp_path / 'sub'
    sub.mkdir()
    (sub / 'inner.py').write_text('import os\nFOO = 42\n')
    return tmp_path


# -----------------------------------------------------------
# search_files
# -----------------------------------------------------------


class TestSearchFiles:
    def test_basic_search(self, searcher: PythonSearcher, tmp_tree: Path):
        results = searcher.search_files('hello', str(tmp_tree))
        assert results
        assert any('hello' in line for _, _, line in results)

    def test_no_match(self, searcher: PythonSearcher, tmp_tree: Path):
        results = searcher.search_files('nonexistent_text_xyz', str(tmp_tree))
        assert results == []

    def test_file_pattern_filter(self, searcher: PythonSearcher, tmp_tree: Path):
        results = searcher.search_files('.*', str(tmp_tree), file_pattern='*.py')
        paths = {r[0].name for r in results}
        assert 'hello.py' in paths
        assert 'readme.md' not in paths

    def test_max_results_respected(self, searcher: PythonSearcher, tmp_tree: Path):
        results = searcher.search_files('.*', str(tmp_tree), max_results=2)
        assert len(results) <= 2

    def test_nonexistent_directory(self, searcher: PythonSearcher):
        results = searcher.search_files('foo', '/nonexistent_dir_xyz')
        assert results == []

    def test_invalid_regex(self, searcher: PythonSearcher, tmp_tree: Path):
        results = searcher.search_files('[invalid', str(tmp_tree))
        assert results == []

    def test_oversized_regex_rejected(self, searcher: PythonSearcher, tmp_tree: Path):
        huge = 'a' * (MAX_USER_REGEX_PATTERN_CHARS + 1)
        assert searcher.search_files(huge, str(tmp_tree)) == []

    def test_case_sensitive(self, searcher: PythonSearcher, tmp_tree: Path):
        results = searcher.search_files('FOO', str(tmp_tree))
        assert results
        # Should NOT match "foo" in lowercase
        searcher.search_files('foo', str(tmp_tree))
        # FOO only exists once — case-sensitive should differ from "foo"
        foobar_results = searcher.search_files('foobar', str(tmp_tree))
        assert foobar_results == []

    def test_case_insensitive(
        self, case_insensitive_searcher: PythonSearcher, tmp_tree: Path
    ):
        results = case_insensitive_searcher.search_files('foo', str(tmp_tree))
        assert results  # Should match FOO


# -----------------------------------------------------------
# search_content
# -----------------------------------------------------------


class TestSearchContent:
    def test_basic_content_search(self, searcher: PythonSearcher):
        content = 'line one\nline two\nline three\n'
        results = searcher.search_content('two', content)
        assert len(results) == 1
        assert results[0] == (2, 'line two')

    def test_no_match(self, searcher: PythonSearcher):
        results = searcher.search_content('xyz', 'abc\ndef\n')
        assert results == []

    def test_invalid_regex(self, searcher: PythonSearcher):
        results = searcher.search_content('[bad', 'some text')
        assert results == []

    def test_multiple_matches(self, searcher: PythonSearcher):
        content = 'apple\nbanana\napricot\n'
        results = searcher.search_content('^a', content)
        assert len(results) == 2

    def test_case_insensitive_content(self, case_insensitive_searcher: PythonSearcher):
        results = case_insensitive_searcher.search_content('HELLO', 'hello world')
        assert len(results) == 1


# -----------------------------------------------------------
# _iter_files
# -----------------------------------------------------------


class TestIterFiles:
    def test_yields_all_files(self, searcher: PythonSearcher, tmp_tree: Path):
        files = list(searcher._iter_files(tmp_tree))
        assert len(files) >= 3

    def test_glob_filter(self, searcher: PythonSearcher, tmp_tree: Path):
        files = list(searcher._iter_files(tmp_tree, '*.md'))
        names = {f.name for f in files}
        assert 'readme.md' in names
        assert 'hello.py' not in names


# -----------------------------------------------------------
# _search_file
# -----------------------------------------------------------


class TestSearchFile:
    def test_single_file(self, searcher: PythonSearcher, tmp_tree: Path):
        import re

        regex = re.compile('hello')
        results = searcher._search_file(tmp_tree / 'hello.py', regex, 100)
        assert results

    def test_max_results_per_file(self, searcher: PythonSearcher, tmp_tree: Path):
        import re

        regex = re.compile('.*')
        results = searcher._search_file(tmp_tree / 'hello.py', regex, 1)
        assert len(results) == 1
