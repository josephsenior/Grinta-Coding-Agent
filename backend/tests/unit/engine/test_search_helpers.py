from __future__ import annotations

from backend.engine.tools._search_helpers import (
    DEFAULT_SEARCH_HEAD_LIMIT,
    paginate_line_output,
    resolve_search_pagination,
)


class TestResolveSearchPagination:
    def test_defaults_to_200(self) -> None:
        offset, head_limit = resolve_search_pagination(None, None)
        assert offset == 0
        assert head_limit == DEFAULT_SEARCH_HEAD_LIMIT

    def test_zero_head_limit_means_unlimited(self) -> None:
        offset, head_limit = resolve_search_pagination(0, 2)
        assert offset == 2
        assert head_limit is None


class TestPaginateLineOutput:
    def test_truncation_notice(self) -> None:
        lines = [f'line-{index}' for index in range(5)]
        output = paginate_line_output(
            lines,
            offset=0,
            head_limit=2,
            empty_message='empty',
        )
        assert 'line-0' in output
        assert 'line-1' in output
        assert '3 more' in output
