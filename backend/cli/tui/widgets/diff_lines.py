"""Draw visible diff lines without constructing a widget tree for every row."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.selection import Selection
from textual.strip import Strip

from backend.cli.theme.cards import (
    DIFF_GUTTER,
    DIFF_GUTTER_ADD,
    DIFF_GUTTER_REM,
    DIFF_HDR,
    DIFF_LINE_ADD_TEXT,
    DIFF_LINE_CTX,
    DIFF_LINE_REM_TEXT,
)

if TYPE_CHECKING:
    from backend.cli.tui.widgets.unified_diff_view import DiffViewRow


class DiffLines(ScrollView):
    """Fixed-height rows; the enclosing diff/transcript owns scrolling."""

    ALLOW_SELECT = True
    DEFAULT_CSS = """
    DiffLines {
        width: 100%;
        height: auto;
        overflow: hidden hidden;
    }
    """

    def __init__(self, rows: list[DiffViewRow], *, gutter_width: int) -> None:
        super().__init__()
        self.can_focus = False
        self._rows = rows
        self._gutter_width = max(4, gutter_width)
        self.virtual_size = Size(0, len(rows))

    def _line_text(self, y: int, width: int | None = None) -> Text:
        row = self._rows[y]
        gutter = {
            'add': DIFF_GUTTER_ADD,
            'rem': DIFF_GUTTER_REM,
        }.get(row.kind, DIFF_GUTTER)
        color = {
            'add': DIFF_LINE_ADD_TEXT,
            'rem': DIFF_LINE_REM_TEXT,
            'hdr': DIFF_HDR,
        }.get(row.kind, DIFF_LINE_CTX)
        sign = {'add': '+', 'rem': '-'}.get(row.kind, ' ')
        sign_color = {'add': '#54efae', 'rem': '#fd8383'}.get(row.kind, gutter)
        background = {'add': '#0a1410', 'rem': '#120c0c'}.get(row.kind)
        line = Text(no_wrap=True, overflow='crop')
        for value in (row.old_no, row.new_no):
            number = '' if value is None else str(value)
            line.append(f'{number:>{self._gutter_width}} ', gutter)
        line.append(f'{sign} ', sign_color)
        line.append(' ' + (row.text or ' ').expandtabs(8) + ' ', color)
        if width is not None:
            line.truncate(width, overflow='crop', pad=True)
        if background:
            line.stylize_before(f'on {background}')
        return line

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if not 0 <= y < len(self._rows):
            return Strip.blank(width, self.rich_style)
        line = self._line_text(y, width)
        selection = self.text_selection
        if selection is not None and (span := selection.get_span(y)) is not None:
            start, end = span
            line.stylize(
                self.screen.get_component_rich_style('screen--selection'),
                start,
                len(line) if end == -1 else end,
            )
        return (
            Strip(line.render(self.app.console))
            .crop_extend(0, width, self.rich_style)
            .apply_offsets(0, y)
        )

    def get_selection(self, selection: Selection) -> tuple[str, str]:
        text = '\n'.join(self._line_text(y).plain for y in range(len(self._rows)))
        return selection.extract(text), '\n'

    def selection_updated(self, selection: Selection | None) -> None:
        self.refresh()
