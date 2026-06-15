"""Orient tool transcript widgets."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static

from backend.cli.orient_tools import OrientLineModel


class OrientLine(Horizontal):
    """Flat one-line render for read-only orientation tools."""

    DEFAULT_CSS = """
    OrientLine {
        width: 100%;
        height: 1;
        margin: 0;
        padding: 0 1;
        border-left: solid #25344f;
        background: transparent;
    }
    OrientLine .orient-gutter {
        width: 14;
        height: 1;
        color: #5a6a8a;
    }
    OrientLine .orient-target {
        width: 1fr;
        height: 1;
        color: #c8d4e8;
    }
    OrientLine .orient-sep {
        width: 3;
        height: 1;
        color: #54597b;
        content-align: center middle;
    }
    OrientLine .orient-result {
        width: 24;
        height: 1;
        color: #969aad;
        content-align: right middle;
    }
    """

    def __init__(self, model: OrientLineModel, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.model = model

    def _gutter_text(self) -> Text:
        return Text.assemble(
            (f'{self.model.icon} ', '#5a6a8a'),
            (self.model.verb.ljust(9)[:9], '#5a6a8a'),
        )

    def _target_text(self) -> Text:
        return Text(self.model.target or '…', style='#c8d4e8')

    def _result_text(self) -> Text:
        return Text(self.model.result or 'completed', style='#969aad')

    def compose(self) -> ComposeResult:
        yield Static(self._gutter_text(), classes='orient-gutter')
        yield Static(self._target_text(), classes='orient-target')
        yield Static(Text('·', style='#54597b'), classes='orient-sep')
        yield Static(self._result_text(), classes='orient-result')

    def set_result(self, result: str) -> None:
        self.model = self.model.with_result(result)
        if not self.is_mounted:
            return
        try:
            self.query_one('.orient-result', Static).update(self._result_text())
        except Exception:
            pass


class OrientBurst(Container):
    """Group-level collapsible for dense runs of orient lines."""

    DEFAULT_CSS = """
    OrientBurst {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0;
        border: transparent;
        background: transparent;
    }
    OrientBurst:focus {
        background: #080f1c;
        border-left: solid #25344f;
    }
    OrientBurst .orient-burst-header {
        width: 100%;
        height: 1;
        padding: 0 1;
        color: #6f83aa;
    }
    OrientBurst .orient-burst-body {
        width: 100%;
        height: auto;
    }
    OrientBurst .orient-burst-body.-hidden {
        display: none;
    }
    """

    can_focus = True
    BINDINGS = [
        ('enter', 'toggle', 'Toggle Expansion'),
        ('space', 'toggle', 'Toggle Expansion'),
    ]

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

    def _header_text(self) -> Text:
        caret = '▸' if self._collapsed else '▾'
        return Text.assemble(
            (f'{caret} ', '#54597b'),
            (f'Exploring {self._area}', '#6f83aa'),
            (f' · {len(self._lines)} lookups', '#969aad'),
        )

    def compose(self) -> ComposeResult:
        yield Static(
            self._header_text(), id='orient-burst-header', classes='orient-burst-header'
        )
        body_classes = (
            'orient-burst-body -hidden' if self._collapsed else 'orient-burst-body'
        )
        with Vertical(id='orient-burst-body', classes=body_classes):
            for model in self._lines:
                yield OrientLine(model)

    def _sync_visibility(self) -> None:
        try:
            header = self.query_one('#orient-burst-header', Static)
            header.update(self._header_text())
            body = self.query_one('#orient-burst-body', Vertical)
        except Exception:
            return
        if self._collapsed:
            body.add_class('-hidden')
        else:
            body.remove_class('-hidden')

    def toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._sync_visibility()

    def action_toggle(self) -> None:
        self.toggle()

    def on_click(self, event: events.Click) -> None:
        if event.widget and (
            event.widget.id == 'orient-burst-header' or event.widget == self
        ):
            self.toggle()
            event.prevent_default()
            event.stop()
