"""Smoke test: mount scan-line transcript rows and dump their summary text."""

from textual.app import App, ComposeResult

from backend.cli.event_rendering.unified_renderer import ActivityRenderer
from backend.cli.tool_display.orient_tools import OrientLineModel
from backend.cli.tui.widgets.activity_card import OrientLine
from backend.cli.tui.widgets.scan_line import EditCard


class TestApp(App):
    def compose(self) -> ComposeResult:
        s = self.console.size
        print(f'\n=== TestApp starting (terminal size {s}) ===\n')

        fc = ActivityRenderer.file_create(path='demo.txt', line_count=2)
        fr = ActivityRenderer.file_read(path='src/main.py', line_range='1:50')
        fe = ActivityRenderer.file_edit(
            verb='Edited', path='src/main.py', line_range='10:20', added=3, removed=1
        )

        for label, card in (
            ('file_create', fc),
            ('file_read', fr),
            ('file_edit', fe),
        ):
            print(f'{label} dataclass:')
            print('  verb:', card.verb)
            print('  detail:', card.detail)
            print('  secondary:', card.secondary)
            print()

        yield EditCard('demo.txt', added=2, is_create=True)
        yield OrientLine(
            OrientLineModel(
                tool='read_file',
                icon='↳',
                verb=fr.verb,
                target=fr.detail,
                result='lines 1–50',
            )
        )
        yield EditCard('src/main.py', added=3, removed=1)


if __name__ == '__main__':
    app = TestApp()
    app.run(headless=True, size=(120, 36))
