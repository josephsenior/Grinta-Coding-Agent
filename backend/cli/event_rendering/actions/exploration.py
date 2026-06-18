"""Action renderers — exploration domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.cli._typing import ActionRenderersHost

    _ActionRenderersBase = ActionRenderersHost
else:
    _ActionRenderersBase = object


from backend.cli._typing import ActionRenderersHost
from backend.cli.tool_display.orient_tools import (
    analyze_action_model,
    find_symbols_action_model,
    glob_action_model,
    grep_action_model,
    lsp_action_model,
    read_symbols_action_model,
)
from backend.ledger.action import (  # noqa: E402
    AnalyzeProjectStructureAction,
    FindSymbolsAction,
    GlobAction,
    GrepAction,
    LspQueryAction,
    ReadSymbolsAction,
)


class _ActionExplorationMixin(_ActionRenderersBase):
    def _render_lsp_query_action(self, action: LspQueryAction) -> None:
        self._queue_orient_line(lsp_action_model(action))
        self.refresh()

    def _render_grep_action(self, action: GrepAction) -> None:
        self._queue_orient_line(grep_action_model(action))
        self.refresh()

    def _render_glob_action(self, action: GlobAction) -> None:
        self._queue_orient_line(glob_action_model(action))
        self.refresh()

    def _render_find_symbols_action(self, action: FindSymbolsAction) -> None:
        self._queue_orient_line(find_symbols_action_model(action))
        self.refresh()

    def _render_read_symbols_action(self, action: ReadSymbolsAction) -> None:
        self._queue_orient_line(read_symbols_action_model(action))
        self.refresh()

    def _render_analyze_project_structure_action(
        self, action: AnalyzeProjectStructureAction
    ) -> None:
        self._queue_orient_line(analyze_action_model(action))
        self.refresh()
