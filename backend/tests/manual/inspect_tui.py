"""Render cards and dump rendered text."""

import asyncio
import sys

from textual.app import App

from backend.cli._event_renderer.unified_renderer import ActivityRenderer
from backend.cli.tui.widgets.activity_card import ActivityCard

# Force UTF-8 stdout
sys.stdout.reconfigure(encoding='utf-8', errors='replace')


async def main():
    fc = ActivityRenderer.file_create('demo.txt', line_count=2)
    fr = ActivityRenderer.file_read('src/main.py', line_range='1:50')
    fe = ActivityRenderer.file_edit(
        'Edited', 'src/main.py', line_range='10:20', added=3, removed=1
    )

    class T(App):
        def compose(self):
            yield ActivityCard(
                verb=fc.verb,
                detail=fc.detail,
                badge_category=fc.badge_category,
                status='ok',
                outcome=fc.secondary,
                collapsed=fc.start_collapsed,
                collapsible=fc.is_collapsible,
                syntax_language=fc.syntax_language,
            )
            yield ActivityCard(
                verb=fr.verb,
                detail=fr.detail,
                badge_category=fr.badge_category,
                status='neutral',
                collapsed=fr.start_collapsed,
                collapsible=fr.is_collapsible,
                syntax_language=fr.syntax_language,
            )
            yield ActivityCard(
                verb=fe.verb,
                detail=fe.detail,
                badge_category=fe.badge_category,
                status='ok',
                outcome=fe.secondary,
                collapsed=fe.start_collapsed,
                collapsible=fe.is_collapsible,
                syntax_language=fe.syntax_language,
            )

    app = T()
    async with app.run_test(size=(120, 20)) as pilot:
        await pilot.pause()
        screen = app.screen
        cards = list(screen.query(ActivityCard).results())
        print(f'Number of cards: {len(cards)}')
        for i, card in enumerate(cards):
            collapsed = card.query_one('#collapsed-row')
            try:
                rendered = collapsed.renderable
                txt = str(rendered)
            except Exception as e:
                txt = f'ERR: {e}'
            try:
                body = card.query_one('#expanded-body')
                body_visible = (not body.has_class('-hidden')) and bool(body.display)
            except Exception:
                body_visible = '?'
            print(f'Card {i}:')
            print(f'  collapsed_row: {txt!r}')
            print(f'  body_visible:  {body_visible}')
            print(f'  card.collapsed: {card._collapsed}')
            print(f'  card.collapsible: {card._collapsible}')
            print(f'  extra_content: {card._extra_content!r}')
            print(f'  classes: {sorted(card.classes)}')


asyncio.run(main())
