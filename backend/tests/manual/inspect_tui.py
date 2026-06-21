"""Render scan-line transcript rows and dump their summary text."""

import asyncio
import sys

from textual.app import App

from backend.cli.tool_display.orient_tools import OrientLineModel
from backend.cli.tui.widgets.activity_card import OrientLine
from backend.cli.tui.widgets.scan_line import EditCard

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


async def main() -> None:
    class T(App):
        def compose(self):
            yield EditCard(
                'src/main.py',
                added=3,
                removed=1,
                is_create=False,
            )
            yield OrientLine(
                OrientLineModel(
                    tool='read_file',
                    icon='↳',
                    verb='Read',
                    target='src/main.py',
                    result='lines 1–50',
                )
            )

    app = T()
    async with app.run_test(size=(120, 20)) as pilot:
        await pilot.pause()
        screen = app.screen
        edits = list(screen.query(EditCard).results())
        reads = list(screen.query(OrientLine).results())
        print(f'Edit cards: {len(edits)}, orient lines: {len(reads)}')
        for card in edits:
            print(f'  EditCard: {card._line_text()}')
        for line in reads:
            print(f'  OrientLine: {line._line_text()}')


asyncio.run(main())
