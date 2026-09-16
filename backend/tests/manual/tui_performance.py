"""Compare the legacy per-row diff tree with virtual lines in a headless TUI.

Run: python -m backend.tests.manual.tui_performance
No provider calls or workspace/session changes are made.
"""

from __future__ import annotations

import asyncio
import json
import time

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from backend.cli.tui.widgets.diff_lines import DiffLines
from backend.cli.tui.widgets.unified_diff_view import DiffViewRow, UnifiedDiffRow


async def measure(*, virtual: bool, count: int = 1000) -> dict:
    rows = [
        DiffViewRow(None, index + 1, 'add', f'line {index}') for index in range(count)
    ]

    class DiffApp(App):
        def compose(self) -> ComposeResult:
            with VerticalScroll():
                if virtual:
                    yield DiffLines(rows, gutter_width=4)
                else:
                    for row in rows:
                        yield UnifiedDiffRow(row, gutter_width=4)

    started = time.perf_counter()
    async with DiffApp().run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        ready_ms = (time.perf_counter() - started) * 1000
        widgets = len(pilot.app.screen.query('*'))
        started = time.perf_counter()
        pilot.app.query_one(VerticalScroll).scroll_end(animate=False, immediate=True)
        await pilot.pause()
        scroll_ms = (time.perf_counter() - started) * 1000
    return {
        'implementation': 'virtual' if virtual else 'legacy',
        'rows': count,
        'widgets': widgets,
        'ready_ms': round(ready_ms, 1),
        'scroll_ms': round(scroll_ms, 1),
    }


async def main() -> None:
    for virtual in (False, True):
        print(json.dumps(await measure(virtual=virtual)), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
