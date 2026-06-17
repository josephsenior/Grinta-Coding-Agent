"""Orient tool transcript widgets."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from backend.cli.orient_tools import OrientLineModel
from backend.cli.theme import CLR_REASONING_SNAP

# Left pipe colors — aligned with exploration activity-card accents.
_ORIENT_PIPE_BY_TOOL: dict[str, str] = {
    'grep': '#2d4a6a',
    'glob': '#2d4a6a',
    'find_symbols': '#2d4a6a',
    'read_symbols': '#2d4a6a',
    'analyze_project_structure': '#2d4a6a',
    'read_file': '#2d4a6a',
    'lsp': '#2d4a6a',
    'web_search': '#3a4a6a',
    'web_fetch': '#3a4a6a',
    'docs_resolve': '#3a3d5a',
    'docs_query': '#3a3d5a',
}

_ORIENT_PREFIX_BY_TOOL: dict[str, str] = {
    'grep': '#5a7a9a',
    'glob': '#5a7a9a',
    'find_symbols': '#5a7a9a',
    'read_symbols': '#5a7a9a',
    'analyze_project_structure': '#5a7a9a',
    'read_file': '#5a7a9a',
    'lsp': '#5a7a9a',
    'web_search': '#6a7a9a',
    'web_fetch': '#6a7a9a',
    'docs_resolve': '#7a7a9a',
    'docs_query': '#7a7a9a',
}


def _pipe_color(tool: str) -> str:
    return _ORIENT_PIPE_BY_TOOL.get(tool, '#2d4a6a')


def _prefix_color(tool: str) -> str:
    return _ORIENT_PREFIX_BY_TOOL.get(tool, '#5a7a9a')


class OrientLine(Container):
    """Single-line exploration tool row — matches ThinkingIndicator chrome."""

    DEFAULT_CSS = """
    OrientLine {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        border: transparent;
        background: #090d18;
        border-left: solid #2d4a6a;
        padding: 0 1 0 2;
    }
    OrientLine > #orient-content {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, model: OrientLineModel, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.model = model
        self.styles.border_left = ('solid', _pipe_color(model.tool))

    def _line_text(self) -> Text:
        prefix = f'{self.model.icon} {self.model.verb}: '
        target = self.model.target or '…'
        result = self.model.result or 'completed'
        return Text.assemble(
            (prefix, _prefix_color(self.model.tool)),
            (target, '#c8d4e8'),
            (' · ', '#54597b'),
            (result, CLR_REASONING_SNAP),
        )

    def compose(self) -> ComposeResult:
        yield Static(self._line_text(), id='orient-content')

    def set_result(self, result: str) -> None:
        self.model = self.model.with_result(result)
        if not self.is_mounted:
            return
        try:
            self.query_one('#orient-content', Static).update(self._line_text())
        except Exception:
            pass


class OrientBurst(Container):
    """Legacy grouped orient container — kept for import compatibility."""

    DEFAULT_CSS = """
    OrientBurst {
        display: none;
    }
    """

    def __init__(
        self,
        area: str,
        lines: list[OrientLineModel],
        *,
        collapsed: bool = True,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._area = area or 'codebase'
        self._lines = list(lines)
        self._collapsed = collapsed
