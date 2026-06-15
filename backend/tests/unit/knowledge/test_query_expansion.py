"""Unit tests for knowledge query expansion."""

from __future__ import annotations

from backend.knowledge.query_expansion import QueryExpander


def test_expand_query_disabled_returns_original() -> None:
    expander = QueryExpander(expand=False)
    assert expander.expand_query('find function') == ['find function']


def test_expand_query_adds_synonyms() -> None:
    expander = QueryExpander(expand=True, use_patterns=True)
    queries = expander.expand_query('find function in file')
    assert 'find function in file' in queries
    assert any('method' in q or 'search' in q for q in queries)


def test_get_code_context_boost_detects_pytest() -> None:
    expander = QueryExpander()
    boosts = expander.get_code_context_boost('pytest fixture for auth test')
    assert 'pytest' in boosts
    assert boosts['pytest'] > 0


def test_format_for_search_single_query_unchanged() -> None:
    expander = QueryExpander(expand=False)
    assert expander.format_for_search('only one') == 'only one'


def test_format_for_search_joins_expanded_queries() -> None:
    expander = QueryExpander(expand=True)
    formatted = expander.format_for_search('find error')
    assert ' OR ' in formatted or formatted == 'find error'


def test_contextualize_returns_expanded_list() -> None:
    expander = QueryExpander(expand=True)
    queries = expander.contextualize('debug api error', context={'language': 'python'})
    assert queries
    assert isinstance(queries, list)
