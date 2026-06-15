"""Instance-method tests for exploration observation mixin."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.cli.event_rendering.observations.exploration import _ObsExplorationMixin
from backend.cli.orient_tools import OrientLineModel


class TestCompleteOrAppendOrient:
    def setup_method(self) -> None:
        self.mixin = _ObsExplorationMixin()
        self.mixin._pending_orient_line = None
        self.lines: list[OrientLineModel] = []
        self.mixin._append_orient_line = self.lines.append
        self.mixin._stop_reasoning = MagicMock()

    def test_completes_pending_orient_line(self) -> None:
        pending = OrientLineModel(
            tool='grep',
            icon='⌕',
            verb='Grepped',
            target='foo',
            result='…',
        )
        self.mixin._pending_orient_line = pending
        fallback = OrientLineModel(
            tool='grep',
            icon='⌕',
            verb='Grepped',
            target='foo',
            result='2 matchs',
        )
        self.mixin._complete_or_append_orient('grep', fallback)
        assert self.mixin._pending_orient_line is None
        assert len(self.lines) == 1
        assert self.lines[0].result == '2 matchs'

    def test_appends_fallback_when_no_pending(self) -> None:
        fallback = OrientLineModel(
            tool='glob',
            icon='◎',
            verb='Globbed',
            target='*.py',
            result='3 files',
        )
        self.mixin._complete_or_append_orient('glob', fallback)
        assert self.lines == [fallback]

    def test_ignores_pending_with_wrong_tool(self) -> None:
        self.mixin._pending_orient_line = OrientLineModel(
            tool='grep',
            icon='⌕',
            verb='Grepped',
            target='x',
            result='…',
        )
        fallback = OrientLineModel(
            tool='glob',
            icon='◎',
            verb='Globbed',
            target='*.py',
            result='1 file',
        )
        self.mixin._complete_or_append_orient('glob', fallback)
        assert self.lines == [fallback]
